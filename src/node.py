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
from typing import List, Dict, Any, Optional, Set, Tuple
from network.message import MessageType
from utils.test_runner import PytestRunner
from network.NetworkFacade import NetworkFacade
import utils.functions as f

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger().setLevel(logging.DEBUG)

IP:str = "0.0.0.0"

URL:int = 1
ZIP:int = 0

HEARTBEAT_INTERVAL:float = 10
TASK_ANNOUNCE_INTERVAL:float = 5
TASK_SEND_TIMEOUT:float = 10
UPDATE_TIMEOUT:float = 10

GIVEN_TASK:int = 1
DIRECTLY_PROJECT :int = 0

EPS: float = 1e-10

class Node:

    def __init__(self, ip:str = IP, port:int = 8000, host:Any = None):

        # base node info
        self.address:Tuple[str,int] = (ip, port)
        self.is_running:bool = False
        self.is_working:bool = False
        self.connected:bool = host == "0"
        self.host = host
        self.outside_ip = os.environ.get("OUTSIDE_IP", ip)
        self.outside_port = os.environ.get("OUTSIDE_PORT", str(port))

        self.urls:Dict[str, Tuple[str,str]] = {} # urls and tokens for each project
        self.project_files:Dict[str,str] = {}               # project name : url/zip : url or zip files

        # network
        self.network_facade:Optional[NetworkFacade] = None

        # task variables
        self.task_queue:asyncio.Queue = asyncio.Queue()
        self.task_priority_queue:asyncio.Queue = asyncio.Queue() #Priority queue for tasks that were being processed by dead nodes
        self.task_responsibilities:Dict[str,Tuple[Tuple[str,int],float]] = {}
        self.task_results:Dict[str,Dict[str,Any]] = {}
        self.external_task:Optional[Tuple[str,str]] = None
        self.expecting_confirm:Dict[str,float] = {}         # task_id : time--> stores the tasks waiting for confirmation
        self.processed_evaluations: Set[str] = set()        # evaluations that were processed in this node
        self.processed_projects: Set[str] = set()           # projects that were processed in this node

        # time variables
        self.last_heartbeat:float = .0
        self.last_task_announce:float = .0

        # stats
        self.tests_passed:int = 0
        self.tests_failed:int = 0
        self.modules:int = 0
        self.evaluation_counter:int = 0

        # results

        # network cache
        self.network_cache:Dict[str, Dict[str,Any]] = {
            "evaluations": {},                              # contains the evaluations and their projects names
            "projects": {},                                 # contains the projects and their status
            "status": {},                                   # contains the status of the nodes
        }

        # Adicionado para tolerância a falhas
        self.last_heartbeat_received: Dict[str, float] = {}  # Rastreia o último heartbeat por nó

    async def start(self):
        "starts the node"

        # start network
        self.network_facade = NetworkFacade(self.address,self.connected)
        await self.network_facade.start()

        self.is_running = True

        # start node tasks
        asyncio.create_task(self.check_heartbeats())
        asyncio.create_task(self.listen())
        asyncio.create_task(self.process_queue())

        logging.info(f"Node started at {self.outside_ip}:{self.outside_port}")

    async def stop(self):
        "stops the node"
        self.is_running = False

        # stop network
        if self.network_facade:
            await self.network_facade.stop()


        logging.info("Node stopped")

    def _get_status(self)-> Dict[str, Any]:
        res:Dict = {
            "failed": self.tests_failed,
            "passed": self.tests_passed,
            "projects": len(self.processed_projects),
            "modules": self.modules,
            "evaluations": list(self.processed_evaluations)
        }
        return res

    def get_network_schema(self) -> Dict[str, List[str]]:
        "returns the network schema"
        return {node: data["net"] for node, data in self.network_cache["status"].items()}

    def get_status(self) -> Dict[str, Any]:
        "returns the status of the node"

        def sum_status(data: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
            "sums the status of all nodes"

            evaluations = set()

            res:Dict[str,int] = {
                "failed": 0,
                "passed": 0,
                "projects": 0,
                "modules": 0,
                "evaluations": 0,
            }

            for node_data in data.values():
                stats = node_data.get("stats", {})
                res["failed"] += stats.get("failed", 0)
                res["passed"] += stats.get("passed", 0)
                res["modules"] += stats.get("modules", 0)

                evaluations = evaluations.union(set(stats.get("evaluations", [])))

            res["projects"] = len( self.network_cache["projects"].keys() )
            res["evaluations"] = len(evaluations)

            return res

        res = {"all":{},"nodes":[]}

        res["nodes"] = [
            {"addr": node, **data["stats"]} for node, data in self.network_cache["status"].items()
        ]
        res["all"] = sum_status(self.network_cache["status"])

        return res

    def _new_evaluation(self,eval_id:str):
        "creates a new evaluation entry"
        self.network_cache["evaluations"][eval_id] = {
            "projects": [],
            "start_time": None,
            "end_time": None
            }

    def _new_project(self, project_name:str, node_addr: str):
        self.network_cache["projects"][project_name] = {
            "node": node_addr,
            "modules": {}
            }

    def _new_module(self,project_name:str, module_name:str):
        self.network_cache["projects"][project_name]["modules"][module_name] = {
            "passed": 0,
            "failed": 0,
            "time": 0,
            "status": "pending"
            }

    def _new_task(self,addr:Tuple[str,int],project_name:str, module_name:str, eval_id: Optional[str] = None):
        "creates a new task entry"
        self.task_results[f"{project_name}::{module_name}"] = {
                "task_id": f"{project_name}::{module_name}",
                "node": addr,
                "project_name": project_name,
                "module": module_name,
                "passed": 0,
                "failed": 0,
                "time": 0
            }
        self.processed_projects.add(project_name)
        if eval_id:
            self.processed_evaluations.add(eval_id)

    #TOCHECK
    async def submit_evaluation(self, zip_bytes:bytes) -> Optional[str]:

        # get evaluation id
        self.evaluation_counter += 1
        eval_id = f"{self.network_facade.node_id}{self.evaluation_counter}" #type: ignore
        node_addr = f"{self.outside_ip}:{self.outside_port}"

        # download evaluation
        eval_dir = os.path.join(os.getcwd(), eval_id)
        if await f.bytes_2_folder(zip_bytes, eval_dir):

            self._new_evaluation(eval_id)
            self.network_cache["evaluations"][eval_id]["start_time"] = time.time()
            project_names = []

            # get amount of folders inside the zip
            for project_name in os.listdir(eval_dir):
                project_path = os.path.join(eval_dir, project_name)
                if os.path.isdir(project_path):

                    # check if project was already evaluated
                    if project_name in self.network_cache["projects"]:

                        # remove project folder
                        await self.cleanup_project(project_path)
                        continue

                    self.network_cache["evaluations"][eval_id]["projects"].append(project_name)

                    file_bytes:bytes = await f.folder_2_bytes(project_path)
                    file_b64 = base64.b64encode(file_bytes).decode('utf-8')
                    self.project_files[project_name] = file_b64

                    self._new_project(project_name, node_addr)

                    self.network_facade.PROJECT_ANNOUNCE( # type: ignore
                        {
                        "project_name": project_name,
                        "api_port": os.environ.get("API_PORT", "5000"),
                        "eval_id": eval_id,
                        }
                    )

                    project_names.append(project_name)

            # retrive modules
            info = {
                "eval_id": eval_id,
                "project_names": project_names
            }

            logging.debug("retrieve tasks")
            asyncio.create_task(self.retrieve_tasks(info, type=ZIP))
            await self._propagate_cache()

            return eval_id

        return None

    async def submit_evaluation_url(self, urls: Optional[List[str]] = None, token: Optional[str] = None) -> Optional[str]:
        "submits a eval to the node using url and token"

        # ensure urls and token are provided
        if not (urls and token):
            logging.error("No urls or token provided")
            return None

        # get evaluation id
        self.evaluation_counter += 1
        eval_id = f"{self.network_facade.node_id}{self.evaluation_counter}" #type: ignore

        # create evaluation entry
        self._new_evaluation(eval_id)

        self.network_cache["evaluations"][eval_id]["start_time"] = time.time()
        asyncio.create_task(self.retrieve_tasks({"eval_id": eval_id,
                                                "urls": urls,
                                                "token": token},
                                                type=URL))

        await self._propagate_cache()
        return eval_id

    async def retrieve_tasks(self, info: Dict[str, Any], type: int = ZIP) -> None:
        """
        retrive tasks (pytest modules) from a project
        type 0: zip
        type 1: github
        """

        eval_id = info["eval_id"]
        node_addr = f"{self.outside_ip}:{self.outside_port}"
        added = False

        if type == URL:
            token = info["token"]
            urls = info["urls"]
            for url in urls:
                logging.debug(f"Downloading {url}")
                res = await self.download_project(url, token, eval_id)

                if not res:
                    continue

                project_name, new_project = res
                logging.info(f"Project {project_name} downloaded")

                self.network_cache["evaluations"][eval_id]["projects"] = list(
                    set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_name}
                )

                if not new_project:
                    continue
                added = True
                self._new_project(project_name, node_addr)

                test_runner = PytestRunner(os.getcwd())
                modules = await test_runner.get_modules(project_name)

                if modules:
                    logging.debug(f"Modules: {modules}")
                    self.network_cache["projects"][project_name]["modules"] = {
                        module: {"passed": 0, "failed": 0, "time": 0, "status": "pending"}
                        for module in modules
                    }

                    # add to task queue
                    for module in modules:
                        await self.task_queue.put((project_name, module))

                await asyncio.sleep(0.01)


        elif type == ZIP:
            projects = info["project_names"]
            logging.info(f"Projects: {projects}")

            test_runner = PytestRunner(os.getcwd())

            for project_name in projects:
                project_path = os.path.join(os.getcwd(), eval_id, project_name)

                # get modules per project
                modules = await test_runner.get_modules(project_path)

                if modules:
                    self.network_cache["projects"][project_name]["modules"] = {
                        module: {"passed": 0, "failed": 0, "time": 0, "status": "pending"}
                        for module in modules
                    }

                    # add to task queue
                    for module in modules:
                        await self.task_queue.put((project_name, module))

            await asyncio.sleep(0.01)

        if not added:
            self.network_cache["evaluations"][eval_id]["end_time"]= time.time()

        await self._propagate_cache()

    def get_evaluation_status(self, eval_id: str) -> Optional[Dict[str,Any]]:
        "return the current state of an evaluation"

        if eval_id not in self.network_cache["evaluations"]:
            return None

        eval_data = self.network_cache["evaluations"][eval_id]
        result = {
            "id": eval_id,
            "start_time": eval_data["start_time"],
            "end_time": eval_data["end_time"],
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

        # iterate through projects
        for project_name in eval_data.get("projects", []):

            project_data = self.network_cache["projects"].get(project_name, {})

            project_passed = sum(m["passed"] for m in project_data.get("modules", {}).values())
            project_failed = sum(m["failed"] for m in project_data.get("modules", {}).values())
            total_tests = project_passed + project_failed

            # Calculate project metrics
            project_result = {
                "node": project_data.get("node", ""),
                "pass_percentage": round(project_passed / max(EPS, total_tests) * 100, 2) if total_tests > 0 else 0,
                "fail_percentage": round(project_failed / max(EPS, total_tests) * 100, 2) if total_tests > 0 else 0,
                "score": "--",
                "modules": project_data.get("modules", {}),
                "executed": 0,
                "executing": 0,
                "pending": 0,
            }

            # iterate through modules
            for module_data in project_data.get("modules", {}).values():

                # update execution status count
                if module_data.get("status") == "pending":
                    project_result["pending"] += 1
                elif module_data.get("status") == "running":
                    project_result["executing"] += 1
                elif module_data.get("status") == "finished":
                    project_result["executed"] += 1

            # if no pending or executing, calculate score
            if project_result["pending"] == 0 and project_result["executing"] == 0 and total_tests > 0:
                project_result["score"] = round(project_passed / total_tests * 20, 2)

            total_passed += project_passed
            total_failed += project_failed

            # add project to final result
            result["projects"][project_name] = project_result

            # update counts
            result["summary"]["executed"] += project_result["executed"]
            result["summary"]["executing"] += project_result["executing"]
            result["summary"]["pending"] += project_result["pending"]

        # finish summary
        total_tests = total_passed + total_failed
        if total_tests > 0:
            result["summary"]["total_passed"] = total_passed
            result["summary"]["total_failed"] = total_failed
            result["summary"]["pass_percentage"] = round(total_passed / total_tests * 100, 2)
            result["summary"]["fail_percentage"] = round(total_failed / total_tests * 100, 2)

        if eval_data["start_time"] and eval_data["end_time"]:
            result["summary"]["time_elapsed"] = eval_data["end_time"] - eval_data["start_time"]

        return result

    def get_all_evaluations(self) -> List[str]:
        "returns all evaluations"
        return list(self.network_cache["evaluations"].keys())

    async def process_queue(self):
        " process task queue"

        logging.debug("Node started processing queue")

        while self.is_running:
            try:
                source = DIRECTLY_PROJECT
                task_id = None
                eval_id = None

                # external tasks are priority
                if self.external_task:
                    project_name, module = self.external_task
                    task_id = f"{project_name}::{module}"
                    self.external_task = None
                    source = GIVEN_TASK

                # If priority queue not empty, it should be handled fisrt
                elif not self.task_priority_queue.empty():
                    # Get one task from the priority queue
                    project_name, module = await asyncio.wait_for(self.task_priority_queue.get(), timeout=1)
                    logging.info(f"Processing high priority task {project_name}::{module}")

                else:
                    project_name, module = await asyncio.wait_for(self.task_queue.get(), timeout=1)

                self.is_working = True
                self.network_cache["projects"][project_name]["modules"][module]["status"] = "running"
                await self._propagate_cache()

                test_runner = PytestRunner(os.getcwd())
                logging.debug(f"Processing {project_name}::{module}")

                result = await test_runner.run_tests(project_name, module)
                if result:

                    self.processed_projects.add(project_name)
                    for e_id, e_data in self.network_cache["evaluations"].items():
                        if project_name in e_data["projects"]:
                            self.processed_evaluations.add(e_id)

                    # update node stats
                    self.tests_passed += result.passed
                    self.tests_failed += result.failed
                    self.modules += 1

                    if source == DIRECTLY_PROJECT:
                        logging.debug(f"Processed {project_name}::{module}")
                        # update stats

                        # update project status
                        self.network_cache["projects"][project_name]["modules"][module]["passed"] = result.passed
                        self.network_cache["projects"][project_name]["modules"][module]["failed"] = result.failed
                        self.network_cache["projects"][project_name]["modules"][module]["status"] = "finished"
                        self.network_cache["projects"][project_name]["modules"][module]["time"] = result.time

                    elif source == GIVEN_TASK:
                        logging.debug(f"Processed {project_name}::{module} from task {task_id}")
                        # update stats
                        if not task_id:
                            logging.error("Task ID not found")
                            continue

                        # update task status
                        self.task_results[task_id]["passed"] = result.passed
                        self.task_results[task_id]["failed"] = result.failed
                        self.task_results[task_id]["time"] = result.time
                        addr = self.task_results[task_id]["node"]

                        # respond to the node that requested the task
                        self.network_facade.TASK_RESULT(addr, self.task_results[task_id]) # type: ignore
                        logging.debug(f"Sending task result to {addr}")

                    for e_id, e_data in self.network_cache["evaluations"].items():
                        if project_name in e_data["projects"]:
                            all_finished = all(
                                self.network_cache["projects"][p]["modules"][m]["status"] == "finished"
                                for p in e_data["projects"]
                                for m in self.network_cache["projects"][p]["modules"]
                            )
                            if all_finished and not e_data["end_time"]:
                                e_data["end_time"] = time.time()

                    await self._propagate_cache()

                else:
                    logging.error(f"Error processing {project_name}::{module}")

                self.is_working = False

            except asyncio.TimeoutError:
                continue

            except asyncio.CancelledError:
                break

            except Exception as e:
                logging.error(f"Error in project processing loop: {e}")

            await asyncio.sleep(0.01)

        logging.debug("Node stopped processing queue")
        return

    async def download_project(self, url: str, token: Optional[str] = None, eval_id: Optional[str] = None) -> Optional[Tuple[str, bool]]:
        "downloads the project from the given url"
        try:
            if url.startswith("https://github.com") :

                res:Optional[str] = await f.download_github_repo(url, token)
                if not res:
                    return None

                # Extract just the project name (base name) from the path
                project_name = os.path.basename(res)

                # check if project name was already processed
                if project_name in self.network_cache["projects"]:
                    logging.info(f"Project {project_name} already processed")
                    if eval_id:
                        self.network_cache["evaluations"].setdefault(eval_id, {"projects": [], "start_time": time.time(), "end_time": None})
                        self.network_cache["evaluations"][eval_id]["projects"] = list(
                            set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_name}
                        )
                        await self._propagate_cache()
                    return project_name, False

                self.urls[project_name] = (url, token or "")

                # anounce new project to nodes
                node_addr = f"{self.outside_ip}:{self.outside_port}"
                self._new_project(project_name, node_addr)
                self.network_facade.PROJECT_ANNOUNCE( # type: ignore
                    {
                    "project_name": project_name,
                    "api_port": os.environ.get("API_PORT", "5000"),
                    "eval_id": eval_id,
                    }
                )
                if eval_id:
                    self.network_cache["evaluations"].setdefault(eval_id, {"projects": [], "start_time": time.time(), "end_time": None})
                    self.network_cache["evaluations"][eval_id]["projects"] = list(
                        set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_name}
                    )
                await self._propagate_cache()

                return project_name, True

            else:
                logging.error(f"Unsupported url: {url}")
                return None

        except Exception as e:
            logging.error(f"Error downloading project: {e}")
            return None

    async def cleanup_project(self, project_name: str):
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

    def get_file(self, file_name: str):
        "get file from task division"

        #return url
        if file_name in self.urls:
            url, token = self.urls[file_name]
            return {"type": URL, "url": url, "token": token}

        # return zip file
        if file_name in self.project_files:
            file_b64 = self.project_files[file_name]
            return {"type": ZIP, "bytes": file_b64}

        # file is not in this node
        return None

    async def connect(self):
        try:

            parts = self.host.split(":")
            ip = parts[0]
            port = int(parts[1])

            await asyncio.wait_for( self.network_facade.connect((ip, port)), timeout=5 ) # type: ignore
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

        if not self.connected:
            await self.connect()

        # start listening for messages
        logging.debug("Node started listening for messages")
        while self.is_running:

            current_time = time.time()

            for task_id, timestamp in list(self.expecting_confirm.items()):
                if current_time - timestamp > TASK_SEND_TIMEOUT:
                    logging.warning(f"Timeout waiting for confirmation of task {task_id}")
                    del self.expecting_confirm[task_id]
                    # Put in priority queue for faster termination
                    await self.add_to_priority_queue(task_id)


            # heartbeat
            if current_time - self.last_heartbeat > HEARTBEAT_INTERVAL:
                try:
                    self.last_heartbeat = current_time
                    self.network_facade.HEARTBEAT({
                        "id": f"{self.outside_ip}:{self.outside_port}",
                        "peers_ip": self.network_facade.get_peers_ip(), # type: ignore
                    })
                    logging.debug("Sent heartbeat")
                except Exception as e:
                    logging.error(f"Error in heartbeat: {e}")

            # anounce task
            if not self.task_queue.empty() and current_time - self.last_task_announce > TASK_ANNOUNCE_INTERVAL:
                self.network_facade.TASK_ANNOUNCE()
                self.last_task_announce = current_time
                logging.debug("Sent task announce")

            # try to read message
            try:
                message, _ = await asyncio.wait_for(self.network_facade.recv(), timeout=1)
                await self.process_message(message)

            except asyncio.CancelledError:
                break
            except asyncio.TimeoutError:
                pass
            except Exception:
                logging.error(f"Error in message listening loop: {traceback.format_exc()}")

            await asyncio.sleep(0.01)

        logging.debug("Node stopped listening")
        return

    async def _propagate_cache(self):
        # send network_cache to all nodes

        node_cache = {
            "addr": f"{self.outside_ip}:{self.outside_port}",
            "peers_ip": self.network_facade.get_peers_ip(), # type: ignore
            "evaluations": self.network_cache["evaluations"],
            "projects": self.network_cache["projects"],
            "stats": self._get_status(),
        }
        self.network_facade.CACHE_UPDATE(node_cache) # type: ignore
        logging.debug("Propagating cache to all nodes")

    async def process_message(self, message: dict):

        cmd = message.get("cmd", None)
        if not cmd:
            logging.error(f"Invalid message: {message}")
            return

        ip = message.get("ip", None)
        port = message.get("port", None)
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
    async def _handle_task_request(self, message: dict, _addr: Tuple[str, int]):
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)

        send = False
        project_name = ""
        module = ""

        if not self.task_priority_queue.empty():
            project_name, module = await self.task_priority_queue.get()
            send = True
        
        elif not self.task_queue.empty():
            project_name, module = await self.task_queue.get()
            send = True
        
        eval_id = None
        for e_id, e_data in self.network_cache["evaluations"].items():
            if project_name in e_data["projects"]:
                eval_id = e_id
                break

        # send the zip file to the node
        data = {
            "project_name": project_name,
            "module": module,
            "api_port": os.environ.get("API_PORT", "5000"),
            "eval_id": eval_id,
        }

        self.expecting_confirm[f"{project_name}::{module}"] = time.time()
        self.task_responsibilities[f"{project_name}::{module}"] = (addr, time.time()) # type: ignore
        self.network_facade.TASK_SEND(addr, data) # type: ignore
        logging.debug(f"Sending task {project_name}::{module} to {addr}")

    async def _handle_cache_update(self, message: dict, _addr: Tuple[str, int]):

        saddr = message["data"]["addr"]
        peers_ip = message["data"]["peers_ip"]
        evaluations = message["data"]["evaluations"]
        projects = message["data"]["projects"]
        stats = message["data"]["stats"]
        self.network_cache["status"][saddr] = {
            "net": peers_ip,
            "stats": stats
        }

        for e_id, e_data in evaluations.items():
            if e_id not in self.network_cache["evaluations"]:
                self.network_cache["evaluations"][e_id] = {
                    "projects": e_data["projects"],
                    "start_time": e_data["start_time"],
                    "end_time": e_data["end_time"]
                }
            else:
                # merge data
                current = self.network_cache["evaluations"][e_id]
                current["projects"] = list(set(current["projects"]) | set(e_data["projects"]))
                if current["start_time"] is None:
                    current["start_time"] = e_data["start_time"]
                if current["end_time"] is None:
                    current["end_time"] = e_data["end_time"]

        for p_name, p_data in projects.items():
            if p_name not in self.network_cache["projects"]:
                self.network_cache["projects"][p_name] = {
                    "node": p_data["node"],
                    "modules": p_data["modules"]
                }
            else:
                #merge projects
                current_modules = self.network_cache["projects"][p_name]["modules"]
                for module_name, module_data in p_data["modules"].items():
                    if module_name not in current_modules or module_data["status"] == "finished":
                        current_modules[module_name] = module_data
        logging.debug(f"Cache updated from {saddr}")

    async def _handle_task_working(self, message: dict, _addr: Tuple[str, int]):
        task_id = message["data"]["task_id"]
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)

        if task_id in self.task_responsibilities:
            if addr == self.task_responsibilities[task_id][0]:
                # update time
                self.task_responsibilities[task_id] = (addr, time.time()) # type: ignore

    async def _handle_task_confirm(self, message: dict, _addr: Tuple[str, int]):
        task_id = message["data"]["task_id"]

        if task_id in self.expecting_confirm:
            del self.expecting_confirm[task_id]
            logging.debug(f"Task {task_id} confirmed")
        else:
            logging.error(f"Task {task_id} not found in expecting confirm")

    async def _handle_task_send(self, message: dict, _addr: Tuple[str, int]):

        # project id is not needed due to cahce :^)

        if self.external_task:
            logging.debug(f"Task {self.external_task} already in progress")
            return

        project_name = message["data"]["info"]["project_name"]
        module = message["data"]["info"]["module"]
        api_port = message["data"]["info"]["api_port"]
        eval_id = message["data"]["info"].get("eval_id")
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)

        def get_file_bytes(project_name: str) -> Optional[Tuple[Any, int]]:
            import requests
            logging.debug(f"Getting file {project_name} from {addr}")
            try:
                url = f"http://{addr[0]}:{api_port}/file/{project_name}"
                response = requests.get(url, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    if response.json()["type"] == URL:
                        # download url from github
                        url = response.json()["url"]
                        token = response.json()["token"]

                        return (url, token), URL
                    file_b64 = response.json()["bytes"]
                    file_bytes = base64.b64decode(file_b64)
                    return file_bytes, ZIP

                # request failed
                logging.error(f"Error getting file: {response.status_code}")
                return None
            except Exception:
                return None

        # check if folder was already downloaded
        if project_name in self.urls or project_name in self.project_files:
            self.external_task = (project_name, module)
            self._new_task(addr, project_name, module, eval_id)
            self.network_facade.TASK_CONFIRM(addr, # type: ignore
                {"task_id": f"{project_name}::{module}"})
            if eval_id:
                self.network_cache["evaluations"].setdefault(eval_id, {"projects": [], "start_time": time.time(), "end_time": None})
                self.network_cache["evaluations"][eval_id]["projects"] = list(
                    set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_name}
                )
                await self._propagate_cache()
            return

        # get file bytes
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, partial(get_file_bytes, project_name))

            if res:
                info, type = res
                node_addr = f"{addr[0]}:{addr[1]}"
                if type == URL:
                    # download url from github
                    url, token = info
                    if await f.download_github_repo(url, token):
                        self.urls[project_name] = (url, token)
                        self._new_project(project_name, node_addr)
                        self._new_module(project_name, module)
                        self.external_task = (project_name, module)
                        self._new_task(addr, project_name, module, eval_id)
                        self.network_facade.PROJECT_ANNOUNCE({ # type: ignore
                            "project_name": project_name,
                            "api_port": os.environ.get("API_PORT", "5000"),
                            "eval_id": eval_id
                        })
                        if eval_id:
                            self.network_cache["evaluations"].setdefault(eval_id, {"projects": [], "start_time": time.time(), "end_time": None})
                            self.network_cache["evaluations"][eval_id]["projects"] = list(
                                set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_name}
                            )
                        await self._propagate_cache()

                elif type == ZIP:
                    file_bytes = info
                    await f.bytes_2_folder(file_bytes, os.path.join(os.getcwd(), project_name))
                    self.project_files[project_name] = base64.b64encode(file_bytes).decode('utf-8')
                    self._new_project(project_name, node_addr)
                    self._new_module(project_name, module)
                    self.external_task = (project_name, module)
                    self._new_task(addr, project_name, module, eval_id)
                    self.network_facade.PROJECT_ANNOUNCE({ # type: ignore
                        "project_name": project_name,
                        "api_port": os.environ.get("API_PORT", "5000"),
                        "eval_id": eval_id
                    })
                    if eval_id:
                        self.network_cache["evaluations"].setdefault(eval_id, {"projects": [], "start_time": time.time(), "end_time": None})
                        self.network_cache["evaluations"][eval_id]["projects"] = list(
                            set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_name}
                        )
                    await self._propagate_cache()

                # notify node
                self.network_facade.TASK_CONFIRM(addr, # type: ignore
                    {"task_id": f"{project_name}::{module}"})
        except Exception:
            logging.error(f"Error handling task send: {traceback.format_exc()}")



    async def _handle_task_result(self, message: dict, _addr: Tuple[str, int]):

        task_id = message["data"]["task_id"]
        project_name = message["data"]["project_name"]
        module = message["data"]["module"]
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)

        if task_id in self.task_responsibilities:
            if addr == self.task_responsibilities[task_id][0]:

                # remove responsability entry
                del self.task_responsibilities[task_id]

                # update project status
                self.network_cache["projects"][project_name]["modules"][module]["passed"] = message["data"]["passed"]
                self.network_cache["projects"][project_name]["modules"][module]["failed"] = message["data"]["failed"]
                self.network_cache["projects"][project_name]["modules"][module]["status"] = "finished"
                self.network_cache["projects"][project_name]["modules"][module]["time"] = message["data"]["time"]

                # update project status
                self.processed_projects.add(project_name)
                for eval_id, eval_data in self.network_cache["evaluations"].items():
                    if project_name in eval_data["projects"]:
                        self.processed_evaluations.add(eval_id)
                        all_finished = all(
                            self.network_cache["projects"][p]["modules"][m]["status"] == "finished"
                            for p in eval_data["projects"]
                            for m in self.network_cache["projects"][p]["modules"]
                        )
                        if all_finished and not eval_data["end_time"]:
                            eval_data["end_time"] = time.time()


                # inform node that sucessfully finished
                logging.debug(f"Received task result from {addr}")
                self.network_facade.TASK_RESULT_REP(addr, # type: ignore
                    {"task_id": task_id})
                await self._propagate_cache()

    async def _handle_project_announce(self, message: dict, _addr: Tuple[str, int]):
        project_name = message["data"]["project_name"]
        api_port = message["data"]["api_port"]
        eval_id = message["data"].get("eval_id")
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)
        if project_name in self.urls or project_name in self.project_files:
            return

        # request project
        try:
            import requests
            url = f"http://{addr[0]}:{api_port}/file/{project_name}"
            response = requests.get(url, headers={"Content-Type": "application/json"})
            if response.status_code == 200:
                node_addr = f"{addr[0]}:{addr[1]}"
                type = response.json()["type"]
                if type == URL:
                    # dowanload url from github
                    url = response.json()["url"]
                    token = response.json()["token"]
                    if res := await f.download_github_repo(url, token):
                        self.urls[res] = (url, token)

                elif type == ZIP:
                    file_bytes = base64.b64decode(response.json()["bytes"])
                    await f.bytes_2_folder(file_bytes, os.path.join(os.getcwd(), project_name))
                    self.project_files[project_name] = response.json()["bytes"]
                else:
                    logging.error(f"Unknown file type: {type}")
                    return


            else:
                logging.error(f"Error getting file: {response.status_code}")
        except Exception as e:
            logging.error(f"Error getting file: {e}")

        # inform node that sucessfully finished
        logging.debug(f"Received project announce from {addr}")

    async def _handle_task_result_rep(self, message: dict, _addr: Tuple[str, int]):
        task_id = message["data"]["task_id"]
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)
        if task_id in self.task_results:
            if addr == self.task_results[task_id]["node"]:
                # remove task entry
                del self.task_results[task_id]

    async def _handle_heartbeat(self, message: dict, _addr: Tuple[str, int]):
        # Registra o heartbeat recebido com o ID do nó
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)
        node_id = message.get("data", {}).get("id", f"{addr[0]}:{addr[1]}")  # Usa o endereço como ID se não houver node_id
        self.last_heartbeat_received[node_id] = time.time()
        self.network_cache["status"][node_id] = {
            "net": message.get("data", {}).get("peers_ip", []),
            "stats": self.network_cache["status"].get(node_id, {}).get("stats", {})
        }
        logging.debug(f"Heartbeat received from {node_id}")


    async def check_heartbeats(self):
        "Verifica periodicamente os heartbeats para detectar falhas"
        while self.is_running:
            current_time = time.time()
            for node_id, last_time in list(self.last_heartbeat_received.items()):
                if current_time - last_time > 3 * HEARTBEAT_INTERVAL:
                    logging.warning(f"Node {node_id} is considered failed.")
                    await self.handle_node_failure(node_id)
                    del self.last_heartbeat_received[node_id]  # Remove o nó falho
                    if node_id in self.network_cache["status"]:
                        del self.network_cache["status"][node_id]
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def handle_node_failure(self, node_id: str):
        "Reatribui tarefas de um nó falho"
        tasks_to_reassign = [task_id for task_id, info in self.task_responsibilities.items()
                            if f"{info[0][0]}:{info[0][1]}" == node_id]
        for task_id in tasks_to_reassign:
            await self.add_to_priority_queue(task_id)
            del self.task_responsibilities[task_id]
            logging.info(f"Reassigned task {task_id} from failed node {node_id}")



    async def add_to_priority_queue(self, task_id: str):
        """Adiciona uma tarefa à fila de prioridade, extraindo project_name e module do task_id"""
        try:
            project_name, module = task_id.split("::")
            await self.task_priority_queue.put((project_name, module))
            logging.info(f"Task {task_id} added to priority queue")
            return True
        except Exception as e:
            logging.error(f"Error adding task to priority queue: {e}")
            return False
