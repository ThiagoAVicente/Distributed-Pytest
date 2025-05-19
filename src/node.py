"""
implements the node class
"""

import asyncio
import logging
import os
import traceback
import base64
import time
from functools import partial
from typing import List, Dict, Any, Optional
from network.message import MessageType
from utils.test_runner import PytestRunner
from network.NetworkFacade import NetworkFacade
import utils.functions as f

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger().setLevel(logging.DEBUG)

IP:str = "0.0.0.0"

URL:int = 1
ZIP:int = 0

HEARTNEAT_INTERVAL:float = 10
TASKANNOUNCE_INTERVAL:float = 5
TASK_SEND_TIMEOUT:float = 10
UPDATE_TIMEOUT:float = 10

GIVEN_TASK:int = 1
DIRECTLY_PROJECT :int = 0

EPS: float = 1e-10

class Node:

    def __init__(self, ip:str = IP, port:int = 8000, host:Any = None):

        # base node info
        self.address:tuple[str,int] = (ip, port)
        self.is_running:bool = False
        self.is_working:bool = False
        self.connected:bool = host == "0" 
        self.host = host
        
        self.urls:Dict[str, tuple[str,str]] = {} # urls and tokens for each project

        # network
        self.network_facade:Optional[NetworkFacade] = None
        self.network_schema:Dict[str,List[str]] = {} # for each node, its peers
        self.updated:bool = False
        self.last_update:float = .0

        # task variables
        self.task_queue:asyncio.Queue = asyncio.Queue()
        self.project_files:Dict[str,str] = {}               # project name : url/zip : url or zip files
        self.task_responsabilities:Dict[str,List[Any]] = {} 
        self.task_results:Dict[str,Dict[str,Any]] = {}
        self.external_task:Optional[tuple[str,str]] = None 
        self.expecting_confirm:Dict[str,float] = {}         # task_id : time--> stores the tasks waiting for confirmation 

        # time variables
        self.last_heartbeat:float = .0
        self.last_task_announce:float = .0

        # stats
        self.projects_processed:int = 0
        self.tests_passed:int = 0
        self.tests_failed:int = 0
        self.modules:int = 0
        self.evaluation_counter:int = 0
        self.general_status:Dict[str, Any] = {}             # contains the status of every node. is updated on hertbeat

        # results
        self.evaluations:Dict[str,Dict[str,Any]] = {}       # contains the agregated results and the names of the projects
        self.projects :Dict[str,Dict[str,Any]] = {}

        # network cache
        self.network_cache:Dict[str, Dict[str,Any]] = {
            "evaluations": {},                              # contains the evaluations and their status
            "projects": {},                                 # contains the projects and their status
        }

    async def start(self):
        "starts the node"

        # start network
        self.network_facade = NetworkFacade(self.address,self.connected)
        await self.network_facade.start()


        self.is_running = True
        logging.info(f"Node started at {self.address}")

    async def stop(self):
        "stops the node"
        self.is_running = False

        # stop network
        if self.network_facade:
            await self.network_facade.stop()

        logging.info(f"Node stopped at {self.address}")

    def _get_status(self)-> Dict[str, Any]:
        res:Dict = {
            "failed": self.tests_failed,
            "passed": self.tests_passed,
            "projects": self.projects_processed,
            "modules": self.modules,
            "evaluations": list(self.evaluations.keys()),
        }
        return res

    def get_network_schema(self) -> Dict[str, List[str]]:
        "returns the network schema"
        res = self.network_schema.copy()
        res[self.address[0]+":"+str(self.address[1])] = self.network_facade.get_peers_ip() # type: ignore
        return res

    def get_status(self) -> Dict[str, Any]:
        "returns the status of the node"

        def sum_status(data:Dict)->Dict[str,int]:
            "sums the status of all nodes"

            evaluations = set()

            res:Dict[str,int] = {
                "failed": 0,
                "passed": 0,
                "projects": 0,
                "evaluations": 0,
            }

            for node in data.values():
                res["failed"] += node["failed"]
                res["passed"] += node["passed"]
                res["modules"] += node["modules"]

                evaluations = evaluations.union(set(node["evaluations"]))

            res["projects"] = len( self.network_cache["projects"].keys() )
            res["evaluations"] = len(evaluations)

            return res

        res = {"all":{},"nodes":[]}

        res["nodes"] = self.general_status
        res["all"] = sum_status(self.general_status)

        return res

    def _new_evaluation(self,eval_id:str):
        "creates a new evaluation entry"
        self.updated = True
        self.evaluations[eval_id] = {
            "id": eval_id,
            "percentage": 0,
            "failed": 0,
            "passed": 0,
            "modules": 0,
            "projects": [],
        }

    def _new_project(self, project_name:str):
        self.updated = True
        self.projects[project_name] = {
            "passed": 0,
            "failed": 0,
            "modules":0,
            "module_info":{} # each module must have tests passed, tests failed and time and a status saying if it is
                             # running, finished or to be run
        }
        
    def _new_module(self,project_name:str, module_name:str):
        self.updated = True
        self.projects[project_name]["module_info"][module_name] = {
            "passed": 0,
            "failed": 0,
            "time": 0,
            "status": "pending",
        }
        
    def _new_task(self,addr:tuple[str,int],project_name:str, module_name:str):
        "creates a new task entry"
        self.updated = True
        self.task_results[f"{project_name}::{module_name}"] = {
            "task_id":f"{project_name}::{module_name}",
            "node":addr,
            "project_name": project_name,
            "module": module_name,
            "passed": 0,
            "failed": 0,
            "time": 0,
        }
            
    async def submit_evaluation(self, zip_bytes:bytes) -> str:

        # get evaluation id
        self.evaluation_counter += 1
        eval_id = self.network_facade.node_id+str(self.evaluation_counter) #type: ignore

        # download evaluation
        if await f.bytes_2_folder(zip_bytes, os.path.join(os.getcwd(),str(eval_id))):

            self._new_evaluation(eval_id)
            pn = []
            # get amount of folders inside the zip
            for project_name in os.listdir(os.path.join(os.getcwd(),str(eval_id))):
                project_path = os.path.join(os.getcwd(),str(eval_id), project_name)
                if os.path.isdir(project_path):

                    # add project name to the evaluation
                    self.evaluations[eval_id]["projects"].append(project_name)

                    # check if project was already evaluated
                    if project_name in self.network_cache["projects"]:

                        # remove project folder
                        await self.cleanup_project(eval_id+"/"+project_name)
                        continue
                    
                    file_bytes:bytes = await f.folder_2_bytes(os.path.join(os.getcwd(),project_name))
                    file_b64 = base64.b64encode(file_bytes).decode('utf-8')
                    self.project_files[project_name] = file_b64
                    
                    self.network_facade.PROJECT_ANNOUNCE( # type: ignore
                        {
                        "project_name":project_name,
                        "api_port": os.environ.get("API_PORT"),
                        }
                    )

                    self._new_project(project_name)

                    pn.append(project_name)

            # retrive modules
            info = {
                "eval_id": eval_id,
                "project_names":pn
            }
            logging.debug("retrieve tasks")
            asyncio.create_task(self.retrive_tasks(info, type=ZIP))
            return eval_id

        return None

    async def submit_evalution_url(self, urls:list[str] = None , token:str = None) -> str:
        "submits a eval to the node using url and token"

        # get evaluation id
        self.evaluation_counter += 1
        eval_id = self.network_facade.node_id+str(self.evaluation_counter) #type: ignore

        # create evaluation entry
        self._new_evaluation(eval_id)


        # ensure urls and token are provided
        if not (urls and token):
            logging.error("No urls or token provided")
            return None

        # download projects
        asyncio.create_task(self.retrive_tasks({"eval_id":eval_id,
                                                "urls":urls,
                                                "token":token},
                                                type=URL))

        # return evaluation id
        return eval_id

    async def retrive_tasks(self, info:Dict[str,Any], type:int = ZIP) -> None:
        """
        retrive tasks (pytest modules) from a project
        type 0: zip
        type 1: github
        """

        if type == URL:
            token = info["token"]
            urls = info["urls"]
            eval_id = info["eval_id"]

            for url in urls:
                logging.debug(f"Downloading {url}")
                res = await self.download_project(url, token)

                if not res:
                    continue
                
                project_name, new_project = res
                
                logging.info(f"Project {project_name} downloaded")
                self.evaluations[eval_id]["projects"].append(project_name)
                
                if not new_project:
                    continue
                    

                test_runner = PytestRunner(os.getcwd())
                modules = await test_runner.get_modules(project_name)
                
                if modules:
                    logging.debug(f"Modules: {modules}")
                    self.projects[project_name]["modules"] = len(modules)

                    # add to task queue
                    for module in modules:

                        # create entry for each module
                        self._new_module(project_name,module)
                        await self.task_queue.put((project_name, module))
                            
                await asyncio.sleep(0.1)

        elif type == ZIP:
            projects = info["project_names"]
            logging.info(f"Projects: {projects}")

            for project_name in projects:

                # get modules per project
                test_runner = PytestRunner(os.getcwd())
                modules = await test_runner.get_modules(project_name)

                if modules:
                    self.projects[project_name]["modules"] = len(modules)

                    # add to task queue
                    for module in modules:

                        # create entry for each module
                        self._new_module(project_name,module)
                        await self.task_queue.put((project_name, module))

    def get_evaluation_status(self, eval_id: str) -> Optional[Dict[str,Any]]:
        "return the current state of an evaluation"

        if eval_id not in self.network_cache["evaluations"]:
            return None

        eval_data = self.network_cache["evaluations"][eval_id]
        result = {
            "id": eval_id,
            "summary": {
                "pass_percentage": 0,
                "fail_percentage": 0,
                "executed": 0,
                "executing": 0,
                "pending": 0,
                "time_elapsed": 0,  # time in seconds
            },
            "projects": {}
        }

        total_passed = 0
        total_failed = 0
        total_modules = 0

        # iterate through projects
        for project_name in eval_data.get("projects", []):
            
            project_data = self.network_cache["projects"].get(project_name, {})

            project_passed = project_data.get("passed", 0)
            project_failed = project_data.get("failed", 0)
            total_tests = project_passed + project_failed

            # Calculate project metrics
            project_result = {
                "pass_percentage": round(project_passed /  max(EPS,total_tests) * 100, 2),
                "fail_percentage": round(project_failed /  max(EPS,total_tests) * 100, 2),
                "score": "--",
                "modules": {},
                "executed": 0,
                "executing": 0,
                "pending": 0,
                "time_elapsed": 0
            }


            # iterate through modules
            for module_name, module_data in project_data.get("module_info", {}).items():
                module_passed = module_data.get("passed", 0)
                module_failed = module_data.get("failed", 0)
                module_total = module_passed + module_failed
                module_time = module_data.get("time", 0)

                module_result = {
                    "passed": module_passed,
                    "failed": module_failed,
                    "pass_percentage": round(module_passed / max(EPS, module_total) * 100, 2),
                    "fail_percentage": round(module_failed /  max(EPS,module_total) * 100, 2),
                    "time": module_time,
                    "status": module_data.get("status", "pending")
                }

                # update execution status count
                if module_data.get("status") == "pending":
                    project_result["pending"] += 1
                elif module_data.get("status") == "running":
                    project_result["executing"] += 1
                elif module_data.get("status") == "finished":
                    project_result["executed"] += 1

                # increase time elapsed
                project_result["time_elapsed"] += module_time

                # add module
                project_result["modules"][module_name] = module_result

            # if no pending or executing, calculate score
            if project_result["pending"] == 0 and project_result["executing"] == 0:
                project_result["score"] = round(project_passed / max(EPS, total_tests) * 20, 2)

            total_passed += project_passed
            total_failed += project_failed
            total_modules += project_data.get("modules", 0)

            # add project to final result
            result["projects"][project_name] = project_result

            # update counts
            result["summary"]["executed"] += project_result["executed"]
            result["summary"]["executing"] += project_result["executing"]
            result["summary"]["pending"] += project_result["pending"]
            result["summary"]["time_elapsed"] += project_result["time_elapsed"]

        # finish summary
        total_tests = total_passed + total_failed
        if total_tests > 0:
            result["summary"]["total_passed"] = total_passed
            result["summary"]["total_failed"] = total_failed
            result["summary"]["pass_percentage"] = round(total_passed / total_tests * 100, 2)
            result["summary"]["fail_percentage"] = round(total_failed / total_tests * 100, 2)

        return result

    def get_all_evaluations(self) -> List[str]:
        "returns all evaluations"
        return list(self.network_cache["evaluations"].keys()) # type: ignore

    async def process_queue(self):
        " process task queue"

        logging.debug("Node started processing queue")

        while self.is_running:
            try:
                source = DIRECTLY_PROJECT
                task_id = None
                # get the next project
                if self.external_task:
                    project_name, module = self.external_task
                    task_id = f"{project_name}::{module}"
                    self.external_task = None
                    source = GIVEN_TASK
                else:
                    project_name, module = await asyncio.wait_for(self.task_queue.get(), timeout=1)
                self.is_working = True
                test_runner = PytestRunner(os.getcwd())
                logging.debug(f"Processing {project_name}::{module}")


                result = await test_runner.run_tests(project_name, module)
                if result:
                    
                    if source == DIRECTLY_PROJECT:
                        logging.debug(f"Processed {project_name}::{module}")
                        # update stats
                        self.tests_passed += result.passed
                        self.tests_failed += result.failed
                        self.modules += 1
    
                        # update project status
                        self.projects[project_name]["passed"] += result.passed
                        self.projects[project_name]["failed"] += result.failed
                        self.projects[project_name]["module_info"][module]["passed"] = result.passed
                        self.projects[project_name]["module_info"][module]["failed"] = result.failed
                        self.projects[project_name]["module_info"][module]["status"] = "finished"
                        self.projects[project_name]["module_info"][module]["time"]   = result.time
                    
                    elif source == GIVEN_TASK:
                        logging.debug(f"Processed {project_name}::{module} from task {task_id}")
                        # update stats
                        self.tests_passed += result.passed
                        self.tests_failed += result.failed
                        self.modules += 1
                        
                        # just to dont get the waning but this is never true
                        if not task_id:
                            logging.error("Task id not found")
                            continue
                            
                        # update task status
                        self.task_results[task_id]["passed"] = result.passed
                        self.task_results[task_id]["failed"] = result.failed
                        self.task_results[task_id]["time"] = result.time
                        
                        addr = self.task_results[task_id]["node"]
                        
                        # respond to the node that requested the task
                        logging.debug(f"Sending task result to {addr}")
                        self.network_facade.TASK_RESULT(addr, self.task_results[task_id]) # type: ignore
                            
                    
                    self.updated = True

                else:
                    logging.error(f"Error processing {project_name}::{module}")

                self.is_working = False


            except asyncio.TimeoutError:
                continue

            except asyncio.CancelledError:
                break

            except Exception as e:
                logging.error(f"Error in project processing loop: {e}")

            await asyncio.sleep(0.1)

        logging.debug("Node stopped processing queue")
        return

    async def download_project(self, url:str, token:str = None) -> Optional[tuple[str,bool]]:
        "downloads the project from the given url"
        try:
            if url.startswith("https://github.com") :
                res:Optional[str] =  await f.download_github_repo(url, token)

                if not res:
                    return None

                # Extract just the project name (base name) from the path
                project_name = os.path.basename(res)

                # check if project name was already processed
                if project_name in self.network_cache["projects"]:
                    logging.info(f"Project {project_name} already processed")
                    # clean project folder
                    #await self.cleanup_project(project_name)
                    return project_name,False
                
                self.urls[project_name] = (url,token)
                
                # anounce new project to nodes
                self.network_facade.PROJECT_ANNOUNCE( # type: ignore
                    {
                    "project_name":project_name,
                    "api_port": os.environ.get("API_PORT"),
                    }
                )

                self._new_project(project_name)

                return project_name,True

            else:
                logging.error(f"Unsupported url: {url}")
                return None

        except Exception as e:
            logging.error(f"Error downloading project: {e}")
            return None

    async def cleanup_project(self,project_name:str):
        " remove project dir "
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._remove_directory, project_name)
        except Exception as e:
            logging.error(f"Error cleaning up project: {e}")
            return False

    def _remove_directory(self, path: str):
            """Remove a directory and all its contents"""
            import shutil
            shutil.rmtree(path, ignore_errors=True)

    def get_file(self,file_name):
        "get file from task division"
        
        #return url
        if file_name in self.urls:
            url,token = self.urls[file_name]
            self.expecting_confirm[file_name] = time.time()
            return {"type":URL,"url":url,"token":token}
            
        # return zip file
        if file_name in self.project_files:
            file_b64 = self.project_files[file_name]
            self.expecting_confirm[file_name] = time.time()
            return {"type":ZIP,"bytes":file_b64}
        
        # file is not in this node
        return None
            
    async def connect(self):
        try:
            
            parts = self.host.split(":")
            ip = parts[0]
            port = int(parts[1])
            
            
            await asyncio.wait_for( self.network_facade.connect((ip,port)), timeout= 5 ) # type: ignore
            self.connected = True
            logging.info("Connected to a network")

        except asyncio.TimeoutError:
            logging.error("Connection timed out.")
            await self.stop()

    async def listen(self):
        "main loop for message listening"
        logging.debug("Node started listening")
        if not self.network_facade or not self.network_facade.is_running():
            raise RuntimeError("Protocol not initialized. Ensure the protocol is started.")

        if time.time() - self.last_update > UPDATE_TIMEOUT:
            self.updated = True

        if not self.connected:
            # stop coroutine till connected
            await self.connect()

        # start listening for messages
        logging.debug("Node started listening for messages")
        while self.is_running:
            
            await asyncio.sleep(0.1)

            # try to prepagate cache
            await self.propagate_cache()

            # heartbeat
            #logging.debug(time.time() - self.last_heartbeat)
            if time.time() - self.last_heartbeat > HEARTNEAT_INTERVAL:
                try:
                    logging.debug("Sending heartbeat")
                    self.last_heartbeat = time.time()
                    self.network_facade.HEARTBEAT() # type: ignore
                except Exception as e:
                    logging.error(f"Error in heartbeat: {e}")

            # anounce task
            if not self.task_queue.empty() and time.time() - self.last_task_announce > TASKANNOUNCE_INTERVAL:
                self.network_facade.TASK_ANNOUNCE()
                logging.debug("Sending task announce")
                self.last_task_announce = time.time()

            # try to read message
            try:
                message, _ = await asyncio.wait_for(self.network_facade.recv(),timeout =1)

                await self.process_message(message)

            except asyncio.CancelledError:
                break
            except asyncio.TimeoutError:
                pass
            except Exception:
                logging.error(f"Error in message listening loop: {traceback.format_exc()}")

        logging.debug("Node stopped listening")
        return
    
    async def propagate_cache(self):
        # send network_cache to all nodes
        
        if self.updated:
            
            # update this node cache
            for eval_id,eval_data in self.evaluations.items():
                self.network_cache["evaluations"][eval_id]=eval_data
    
            for project_name,project_data in self.projects.items():
                self.network_cache["projects"][project_name]=project_data
        
            logging.debug("Propagating cache")
            node_cache = {
                "addr": f"{self.address[0]}:{self.address[1]}",
                "peers_ip": self.network_facade.get_peers_ip(), # type: ignore
                "evaluations": self.evaluations,
                "projects": self.projects,
                "node_stats": self._get_status(),
            }
            self.network_facade.CACHE_UPDATE(node_cache) # type: ignore
            self.updated = False
            self.last_update = time.time()
        
    async def process_message(self, message:dict):

        cmd = message.get("cmd",None)
        if not cmd:
            logging.error(f"Invalid message: {message}")
            return
            
        ip = message.get("ip",None)
        port = message.get("port",None)
        if not ip or not port:
            logging.error(f"Invalid message: {message}")
            return
            
        addr = (ip, port)

        if cmd == MessageType.TASK_ANNOUNCE.name:
            # process project announce
            logging.debug(f"Project announce from {addr}")
            if not self.is_working and self.task_queue.empty():
                logging.debug("Requesting task")
                self.network_facade.TASK_REQUEST(addr) # type: ignore

        elif cmd == MessageType.TASK_REQUEST.name:
            # process task request
            logging.debug(f"Task request from {addr}: {message}")
            await self._handle_task_request(message, addr)

        elif cmd == MessageType.TASK_SEND.name:
            logging.info(f"Received task from {addr}")
            await self._handle_task_send(message, addr)
            
        elif cmd == MessageType.CONNECT.name:
            logging.info(f"Received connect request from {addr}")
            self.network_facade.CONNECT_REP(addr) # type: ignore

        elif cmd == MessageType.HEARTBEAT.name:
            logging.info(f"Received heartbeat from {addr}")
            await self._handle_heartbeat(message, addr)
            
        elif cmd == MessageType.TASK_RESULT.name:
            logging.debug(f"Received task result from {addr}")
            await self._handle_task_result(message, addr)
           
        elif cmd == MessageType.TASK_CONFIRM.name:
            # confirm task
           await self._handle_task_confirm(message, addr)
           
        elif cmd == MessageType.CACHE_UPDATE.name:
            await self._handle_cache_update(message, addr)
            
        elif cmd == MessageType.TASK_WORKING.name:
            # update task working
            await self._handle_task_working(message, addr)
            
        elif cmd == MessageType.PROJECT_ANNOUNCE.name:
            await self._handle_project_announce(message, addr)
           
    # handlers
    async def _handle_task_request(self, message:dict, addr:tuple[str,int]):
        if not self.task_queue.empty():
            project_name, module = await self.task_queue.get()
            
            # send the zip file to the node
            data = {
                "project_name": project_name,
                "module": module,
                "api_port":os.environ.get("API_PORT"),
            }
            
            self.expecting_confirm[f"{project_name}::{module}"] = time.time()
            self.network_facade.TASK_SEND(addr,data) # type: ignore
            logging.debug(f"Sending task {project_name}::{module} to {addr}")

    async def _handle_cache_update(self, message:dict, addr:tuple[str,int]):
        
        # update evaluations
        # group node cache
        # -addr ( string with "ip:port")
        # -peers_ip ( a list )
        # -evaluations ( self.evaluations )
        # -projects ( self.projects )
        # -node_stats
        
        saddr = message["data"]["addr"]
        peers_ip = message["data"]["peers_ip"]
        evaluations = message["data"]["evaluations"]
        projects = message["data"]["projects"]
        node_stats = message["data"]["node_stats"]
        
        #logging.debug(message)
        
        # update network cache
        self.network_schema[saddr] = peers_ip
        for evaluation_id , evaluation in evaluations.items():
            
            # dont update evaluation if it is from this node_stats
            if evaluation_id in self.evaluations:
                continue
                
            self.network_cache["evaluations"][evaluation_id] = evaluation
        
        self.general_status[saddr] = node_stats

        for project_name, project in projects.items():
            
            # dont update project if it is from this node_stats
            if project_name in self.projects:
                continue
            
            self.network_cache["projects"][project_name]= project
        
        
        # TODO: update node last heartbeat
        logging.debug("Updated node cache")

    async def _handle_task_working(self,message:dict,addr:tuple[str,int]):
        task_id = message["data"]["task_id"]
        if task_id in self.task_responsabilities:
            if addr == self.task_responsabilities[task_id][0]:
                # update time
                self.task_responsabilities[task_id][1] = time.time()

    async def _handle_task_confirm(self, message:dict, addr:tuple[str,int]):
        task_id = message["data"]["task_id"]
        addr = (message["ip"], int(message["port"]))

        if task_id in self.expecting_confirm:
            del self.expecting_confirm[task_id]
            
            # mark responsability
            self.task_responsabilities[task_id] = [addr,time.time()]
            
            logging.debug(f"Task {task_id} confirmed")
        else:
            logging.error(f"Task {task_id} not found in expecting confirm")  

    async def _handle_task_send(self, message:dict, addr:tuple[str,int]):

        # project id is not needed due to cahce :^)
         
        if self.external_task:
            logging.debug(f"Task {self.external_task} already in progress")
            return

        project_name = message["data"]["info"]["project_name"]
        module = message["data"]["info"]["module"]
        api_port = message["data"]["info"]["api_port"]

        def get_file_bytes(project_name) -> Optional[tuple[Any,int]]:
            import requests
            logging.debug(f"Getting file {project_name} from {addr}")
            try:
                url = f"http://{addr[0]}:{api_port}/file/{project_name}"
                headers = {
                    "Content-Type": "application/json",
                }
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    if response.json()["type"] == URL:
                        # download url from github
                        url = response.json()["url"]
                        token = response.json()["token"]
                        
                        return (url,token),URL
                    file_b64 = response.json()["bytes"]
                    file_bytes = base64.b64decode(file_b64)
                    return file_bytes,ZIP
                else:
                    logging.error(f"Error getting file: {response.status_code}")
                    return None
            except Exception:
                return None
                
        # check if folder was already downloaded
        if project_name in self.urls or project_name in self.project_files:
            self.external_task = ((project_name, module))
            self._new_task( addr,project_name,module)
            self.network_facade.TASK_CONFIRM(addr, # type: ignore
                {"task_id":f"{project_name}::{module}"}) 

        file_bytes:bytes = None
        # get file bytes
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, partial(get_file_bytes, project_name))
        except Exception:
            pass

        if res:
            info, type = res
            if type == URL:
                # download url from github
                url,token = info
                await f.download_github_repo(url, token)
                        
                # add task
                self.external_task = ((project_name, module))
                self._new_task(addr,project_name,module)

            elif type == ZIP:
                file_bytes = info
                await f.bytes_2_folder(file_bytes, os.path.join(os.getcwd(), project_name))
                self.external_task = ((project_name, module))
                self._new_task(addr,project_name,module)
            
            else:
                return
            # notify node 
            self.network_facade.TASK_CONFIRM(addr, # type: ignore
                {"task_id":f"{project_name}::{module}"}) 
    
    async def _handle_task_result(self, message:dict, addr:tuple[str,int]):
        
        task_id = message["data"]["task_id"]
        project_name = message["data"]["project_name"]
        module = message["data"]["module"]
        
        if task_id in self.task_responsabilities:
            if addr == self.task_responsabilities[task_id][0]:
                
                # remove responsability entry
                del self.task_responsabilities[task_id]
                
                # update project status
                self.projects[project_name]["module_info"][module]["passed"] = message["data"]["passed"]
                self.projects[project_name]["module_info"][module]["failed"] = message["data"]["failed"]
                self.projects[project_name]["module_info"][module]["status"] = "finished"
                self.projects[project_name]["module_info"][module]["time"] = message["data"]["time"]
                self.projects[project_name]["passed"] += message["data"]["passed"]
                self.projects[project_name]["failed"] += message["data"]["failed"]
                
                self.updated = True
                
                # inform node that sucessfully finished
                logging.debug(f"Recieved task result from {addr}")
                self.network_facade.TASK_RESULT_REP(addr, # type: ignore
                    {"task_id": task_id})
    
    async def _handle_project_announce(self, message:dict, addr:tuple[str,int]):
        project_name = message["data"]["project_name"]
        api_port = message["data"]["api_port"]
        ip = message["ip"]

        if project_name in self.urls or project_name in self.project_files:
            return
            
        # request project
        import requests
        try:
            url = f"http://{ip}:{api_port}/file/{project_name}"
            headers = {
                "Content-Type": "application/json",
            }
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                
                type = response.json()["type"]
                if type == URL:
                    # dowanload url from github
                    url = response.json()["url"]
                    token = response.json()["token"]
                    res = await f.download_github_repo(url, token)
                    if res:
                        self.urls[res]= (url,token)

                elif type == ZIP:
                    file_b64 = response.json()["bytes"]
                    file_bytes = base64.b64decode(file_b64)
                    await f.bytes_2_folder(file_bytes, os.path.join(os.getcwd(), project_name))
                    self.project_files[project_name] = file_b64
                else:
                    logging.error(f"Unknown file type: {type}")
                    return
                
                
            else:
                logging.error(f"Error getting file: {response.status_code}")
        except Exception as e:
            logging.error(f"Error getting file: {e}")

        # inform node that sucessfully finished
        logging.debug(f"Recieved project announce from {addr}")

    async def _handle_task_result_rep(self, message:dict, addr:tuple[str,int]):
        task_id = message["data"]["task_id"]
        if task_id in self.task_results:
            if addr == self.task_results[task_id]["node"]:
                # remove task entry
                del self.task_results[task_id]

    async def _handle_heartbeat(self, message:dict, addr:tuple[str,int]):
        # TODO 
        pass