"""
implements the node class
"""
import shutil
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
from network.Network import Network
import utils.functions as f

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger().setLevel(logging.DEBUG)

IP:str = "0.0.0.0"

URL:int = 1
ZIP:int = 0

HEARTBEAT_INTERVAL:float = 5
UPDATE_INTERVAL:float = 5
TASK_ANNOUNCE_INTERVAL:float = 5

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
        self.network:Optional[Network] = None

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
        self.last_update:float = .0

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
        self.last_heartbeat_received: Dict[str, float] = {}         # Rastreia o último heartbeat por nó
        self.response_times: Dict[tuple[Any,Any], List[float]] = {}     # Tempos de resposta por nó (addr: lista de tempos)
        self.response_timeout: float = 5.0                          # Valor inicial do timeout
        self.timeout_update_interval: float = 10.0                  # Intervalo para atualizar o timeout
        self.last_timeout_update: float = time.time()               # Última atualização do timeout

        # Election tracking
        self.active_elections: Dict[str, Dict[str, float]] = {}  # failed_node_id -> {candidate_id: timestamp}

    async def start(self):
        "starts the node"

        # start network
        self.network = Network(self.address,self.connected)
        await self.network.start()

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
        if self.network:
            await self.network.stop()


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
        d = {node: data["net"] for node, data in self.network_cache["status"].copy().items()}
        d[f"{self.outside_ip}:{self.outside_port}"] = self.network.get_peers_ip() # type: ignore
        return d

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

        stats_copy = self.network_cache["status"].copy()
        stats_copy[f"{self.outside_ip}:{self.outside_port}"] = {}
        stats_copy[f"{self.outside_ip}:{self.outside_port}"]["stats"] = self._get_status()

        res["nodes"] = [
            {"addr": node, **data["stats"]} for node, data in stats_copy.items()
        ]
        res["nodes"].append
        res["all"] = sum_status(stats_copy)

        return res

    def _new_evaluation(self,eval_id:str):
        "creates a new evaluation entry"
        self.network_cache["evaluations"][eval_id] = {
            "projects": [],
            "start_time": None,
            "end_time": None
            }

    def _new_project(self, project_id:str, node_addr: str, project_name:str):
        self.network_cache["projects"][project_id] = {
            "project_name": project_name,
            "node": node_addr,
            "modules": {}
            }

    def _new_module(self,project_id:str, module_name:str):
        self.network_cache["projects"][project_id]["modules"][module_name] = {
            "passed": 0,
            "failed": 0,
            "time": 0,
            "status": "pending"
            }

    def _new_task(self,addr:Tuple[str,int],project_id:str, module_name:str, eval_id: Optional[str] = None):
        "creates a new task entry"
        self.task_results[f"{project_id}::{module_name}"] = {
                "task_id": f"{project_id}::{module_name}",
                "node": addr,
                "project_id": project_id,
                "module": module_name,
                "passed": 0,
                "failed": 0,
                "time": 0
            }
        self.processed_projects.add(project_id)
        if eval_id:
            self.processed_evaluations.add(eval_id)

    #TOCHECK
    async def submit_evaluation(self, zip_bytes:bytes) -> Optional[str]:

        # get evaluation id
        self.evaluation_counter += 1
        eval_id = f"{self.network.node_id}{self.evaluation_counter}" #type: ignore
        node_addr = f"{self.outside_ip}:{self.outside_port}"

        # download evaluation
        project_names =  await f.bytes_2_folder(zip_bytes)
        project_ids = []

        for project_name in project_names:
            self._new_evaluation(eval_id)
            self.network_cache["evaluations"][eval_id]["start_time"] = time.time()
            project_id = str(time.time()) + self.network.node_id # type: ignore
            project_ids.append(project_id)

            # move project_name to project_id
            shutil.move(project_name, project_id)

            self.network_cache["evaluations"][eval_id]["projects"].append(project_id)

            file_bytes:bytes = await f.folder_2_bytes(project_id)
            file_b64 = base64.b64encode(file_bytes).decode('utf-8')
            self.project_files[project_id] = file_b64

            self._new_project(project_id, node_addr,project_name)

            self.network.PROJECT_ANNOUNCE( # type: ignore
                {
                "project_id": project_id,
                "api_port": os.environ.get("API_PORT", "5000"),
                }
            )

        await self._propagate_cache()

        # retrive modules
        info = {
            "eval_id": eval_id,
            "project_ids": project_ids
        }

        logging.debug("retrieve tasks")
        asyncio.create_task(self.retrieve_tasks(info, type=ZIP))

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
        eval_id = f"{self.network.node_id}{self.evaluation_counter}" #type: ignore

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
        added = False # marks if any project was added

        if type == URL:
            token = info["token"]
            urls = info["urls"]
            for url in urls:
                logging.debug(f"Downloading {url}")
                res = await self.download_project(url, token, eval_id)

                if not res:
                    continue

                project_id, project_name = res
                logging.info(f"Project {project_id} downloaded")

                self.network_cache["evaluations"][eval_id]["projects"] = list(
                    set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_id}
                )

                added = True
                self._new_project(project_id, node_addr, project_name)

                test_runner = PytestRunner(os.getcwd())
                modules = await test_runner.get_modules(project_id)

                if modules:
                    logging.debug(f"Modules: {modules}")
                    self.network_cache["projects"][project_id]["modules"] = {
                        module: {"passed": 0, "failed": 0, "time": 0, "status": "pending"}
                        for module in modules
                    }

                    # add to task queue
                    for module in modules:
                        await self.task_queue.put((project_id, module))

            await asyncio.sleep(0.01)

        elif type == ZIP:
            projects = info["project_ids"]
            logging.info(f"Projects: {projects}")

            test_runner = PytestRunner(os.getcwd())

            for project_id in projects:
                project_path = os.path.join(os.getcwd(), project_id)

                # get modules per project
                modules = await test_runner.get_modules(project_path)

                if modules:
                    self.network_cache["projects"][project_id]["modules"] = {
                        module: {"passed": 0, "failed": 0, "time": 0, "status": "pending"}
                        for module in modules
                    }
                    added = True
                    # add to task queue
                    for module in modules:
                        await self.task_queue.put((project_id, module))

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
            "time_elapsed": "--",
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
        for project_id in eval_data.get("projects", []):

            project_data = self.network_cache["projects"].get(project_id, {})
            project_name = project_data.get("project_name", "Unknown Project")
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
            result["time_elapsed"] = eval_data["end_time"] - eval_data["start_time"]

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

                # external tasks are priority
                if self.external_task:
                    project_id, module = self.external_task
                    task_id = f"{project_id}::{module}"
                    self.external_task = None
                    source = GIVEN_TASK

                # If priority queue not empty, it should be handled fisrt
                elif not self.task_priority_queue.empty():
                    # Get one task from the priority queue
                    project_id, module = await asyncio.wait_for(self.task_priority_queue.get(), timeout=1)
                    logging.info(f"Processing high priority task {project_id}::{module}")

                else:
                    project_id, module = await asyncio.wait_for(self.task_queue.get(), timeout=1)

                self.is_working = True
                self.network_cache["projects"][project_id]["modules"][module]["status"] = "running"
                await self._propagate_cache()

                test_runner = PytestRunner(os.getcwd())
                logging.debug(f"Processing {project_id}::{module}")

                result = await test_runner.run_tests(project_id, module)
                if result:

                    self.processed_projects.add(project_id)
                    for e_id, e_data in self.network_cache["evaluations"].items():
                        if project_id in e_data["projects"]:
                            self.processed_evaluations.add(e_id)

                    # update node stats
                    self.tests_passed += result.passed
                    self.tests_failed += result.failed
                    self.modules += 1

                    if source == DIRECTLY_PROJECT:
                        logging.debug(f"Processed {project_id}::{module}")
                        # update stats

                        # update project status
                        self.network_cache["projects"][project_id]["modules"][module]["passed"] = result.passed
                        self.network_cache["projects"][project_id]["modules"][module]["failed"] = result.failed
                        self.network_cache["projects"][project_id]["modules"][module]["status"] = "finished"
                        self.network_cache["projects"][project_id]["modules"][module]["time"] = result.time

                    elif source == GIVEN_TASK:
                        logging.debug(f"Processed {project_id}::{module} from task {task_id}")
                        # update stats
                        if not task_id:
                            logging.error("Task ID not found")
                            continue

                        # update task status
                        addr = self.task_results[task_id]["node"]

                        # send task results via http on
                        url = f"http://{addr[0]}:{addr[1]}/task"
                        info = {
                            "task_id": task_id,
                            "passed": result.passed,
                            "failed": result.failed,
                            "time": result.time,
                            "project_id": project_id,
                            "module": module,
                            "ip": self.outside_ip,
                            "port": self.outside_port,
                        }

                        await asyncio.get_event_loop().run_in_executor(
                            None,
                            partial(self.send_http_post, url, info)
                        )

                        del self.task_results[task_id]
                        logging.debug(f"Sent task result to {addr}")

                    for e_id, e_data in self.network_cache["evaluations"].items():
                        if project_id in e_data["projects"]:
                            all_finished = all(
                                self.network_cache["projects"][p]["modules"][m]["status"] == "finished"
                                for p in e_data["projects"]
                                for m in self.network_cache["projects"][p]["modules"]
                            )
                            if all_finished and not e_data["end_time"]:
                                e_data["end_time"] = time.time()

                                # clear project files
                                for p_id in e_data["projects"]:
                                    if p_id in self.urls:
                                        del self.urls [p_id]
                                    else:
                                        del self.project_files[p_id]
                                    self._remove_directory(p_id)


                    await self._propagate_cache()


                else:
                    logging.error(f"Error processing {project_id}::{module}")


                # update project status
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

    def send_http_post(self,url:str,info:dict):
        "sends a post request to the given url with the given info"
        try:
            import requests
            response = requests.post(url, json=info)
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Error sending post request: {response.status_code}")
                return None
        except Exception as e:
            logging.error(f"Error sending post request: {e}")
            return None

    async def download_project(self, url: str, token: str , eval_id: str) -> Optional[Tuple[str, str]]:
        "downloads the project from the given url"
        try:
            if url.startswith("https://github.com") :

                project_id = str(time.time()) + self.network.node_id # type: ignore
                res:Optional[str] = await f.download_github_repo(url, token, project_id)

                if not res:
                    return None

                project_name = res

                self.urls[project_id] = (url, token or "")

                # anounce new project to nodes
                node_addr = f"{self.outside_ip}:{self.outside_port}"
                self._new_project(project_id, node_addr, project_name)
                self.network.PROJECT_ANNOUNCE( # type: ignore
                    {
                    "project_id": project_id,
                    "api_port": os.environ.get("API_PORT", "5000"),
                    }
                )
                self.network_cache["evaluations"].setdefault(eval_id, {"projects": [], "start_time": time.time(), "end_time": None})
                self.network_cache["evaluations"][eval_id]["projects"] = list(
                    set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_id}
                )
                await self._propagate_cache()

                return project_id,  project_name

            else:
                logging.error(f"Unsupported url: {url}")
                return None

        except Exception as e:
            logging.error(f"Error downloading project: {e}")
            return None


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

            await asyncio.wait_for( self.network.connect((ip, port)), timeout=5 ) # type: ignore
            self.connected = True
            logging.info("Connected to a network")

        except asyncio.TimeoutError:
            logging.error("Connection timed out.")
            await self.stop()

    def get_active_evaluations_for_node(self, node_id: str) -> Dict[str, List[str]]:
        """
        Identifica avaliações que estavam ativas no nó falho
        Retorna: {eval_id: [project_ids]}
        """
        active_evaluations = {}

        logging.info(f"Looking for active evaluations for node {node_id}")

        # Check if we have node_id in status cache to get its address
        node_addr = None
        if node_id in self.network_cache["status"]:
            node_addr = self.network_cache["status"][node_id].get("addr")
            logging.info(f"Found address {node_addr} for node {node_id} in cache")

        # If we still don't have an address but have peers, try to find it there
        if not node_addr and hasattr(self.network, 'peers') and node_id in self.network.peers: # type: ignore
            peer_addr = self.network.peers[node_id] # type: ignore
            node_addr = f"{peer_addr[0]}:{peer_addr[1]}"
            logging.info(f"Found address {node_addr} for node {node_id} in peers")

        # Start by collecting all evaluations that are not completed
        # (where end_time is None)
        active_eval_ids = []
        for eval_id, eval_data in self.network_cache["evaluations"].items():
            if eval_data.get("end_time") is None:
                active_eval_ids.append(eval_id)
                logging.info(f"Found active evaluation: {eval_id}")

        logging.info(f"Total active evaluations found: {len(active_eval_ids)}")

        # For each active evaluation, find its projects
        for eval_id in active_eval_ids:
            eval_data = self.network_cache["evaluations"][eval_id]
            eval_projects = []

            for project_id in eval_data.get("projects", []):
                if project_id in self.network_cache["projects"]:
                    project_data = self.network_cache["projects"][project_id]
                    project_node = project_data.get("node", "")

                    # Check if this project belongs to the failed node
                    belongs_to_node = False

                    # Try different matching strategies
                    if project_node == node_id or (node_addr and project_node == node_addr):
                        belongs_to_node = True

                    if belongs_to_node:
                        # Check if there are pending or running modules
                        has_active_modules = False
                        for module_data in project_data.get("modules", {}).values():
                            if module_data.get("status") in ["pending", "running"]:
                                has_active_modules = True
                                break

                        if has_active_modules:
                            eval_projects.append(project_id)
                            logging.info(f"Project {project_id} belongs to node {node_id} and has active modules")

            # If we found projects for this evaluation, add it to the result
            if eval_projects:
                active_evaluations[eval_id] = eval_projects

        # Add any current evaluations from node status
        if node_id in self.network_cache["status"]:
            node_stats = self.network_cache["status"][node_id].get("stats", {})
            node_evaluations = node_stats.get("evaluations", [])

            if node_evaluations:
                logging.info(f"Node {node_id} has evaluations in its stats: {node_evaluations}")

                # For each evaluation the node was working on
                for eval_id in node_evaluations:
                    if eval_id not in active_evaluations and eval_id in self.network_cache["evaluations"]:
                        eval_data = self.network_cache["evaluations"][eval_id]

                        # Check if evaluation is still active
                        if eval_data.get("end_time") is None:
                            # Find any projects with active modules
                            eval_projects = []

                            for project_id in eval_data.get("projects", []):
                                if project_id in self.network_cache["projects"]:
                                    project_data = self.network_cache["projects"][project_id]

                                    # Check if there are pending or running modules
                                    has_active_modules = False
                                    for module_data in project_data.get("modules", {}).values():
                                        if module_data.get("status") in ["pending", "running"]:
                                            has_active_modules = True
                                            break

                                    if has_active_modules:
                                        eval_projects.append(project_id)

                            if eval_projects:
                                active_evaluations[eval_id] = eval_projects
                                logging.info(f"Added evaluation {eval_id} from node stats with projects {eval_projects}")

        if active_evaluations:
            logging.info(f"Found active evaluations for node {node_id}: {active_evaluations}")
        else:
            logging.warning(f"No active evaluations found for node {node_id}")

        return active_evaluations

    async def listen(self):
        "main loop for message listening"
        logging.debug("Node started listening")

        if not self.network or not self.network.is_running():
            raise RuntimeError("Protocol not initialized. Ensure the protocol is started.")

        if not self.connected:
            await self.connect()

        # start listening for messages
        logging.debug("Node started listening for messages")
        while self.is_running:

            current_time = time.time()

            # Atualizar o timeout dinamico
            await self.update_response_timeout()

            for task_id, timestamp in list(self.expecting_confirm.items()):
                if current_time - timestamp > self.response_timeout:
                    logging.warning(f"Timeout waiting for confirmation of task {task_id}")
                    del self.expecting_confirm[task_id]
                    # Put in priority queue for faster termination
                    await self.add_to_priority_queue(task_id)

            # heartbeat
            if current_time - self.last_heartbeat > HEARTBEAT_INTERVAL:
                try:
                    self.last_heartbeat = current_time
                    self.network.HEARTBEAT({
                        "id": self.network.node_id, # type: ignore",
                        "peers_ip": self.network.get_peers_ip(), # type: ignore
                    })
                    logging.debug("Sent heartbeat")
                except Exception as e:
                    logging.error(f"Error in heartbeat: {e}")

            if current_time - self.last_update > UPDATE_INTERVAL:
                await self._propagate_cache()

            # anounce task
            if not self.task_queue.empty() and current_time - self.last_task_announce > TASK_ANNOUNCE_INTERVAL:
                self.network.TASK_ANNOUNCE()
                self.last_task_announce = current_time
                logging.debug("Sent task announce")

            # try to read message
            try:
                message, _ = await asyncio.wait_for(self.network.recv(), timeout=1)
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
            "peers_ip": self.network.get_peers_ip(), # type: ignore
            "evaluations": self.network_cache["evaluations"],
            "projects": self.network_cache["projects"],
            "stats": self._get_status(),
        }
        self.network.CACHE_UPDATE(node_cache) # type: ignore
        self.last_update = time.time()
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
        current_time = time.time()
        send_time = message.get("timestamp", None)

        # Registar tempo de resposta com timestamp
        if send_time:
            response_time = max(0.001, current_time - send_time) # Garantir que não seja negativo
            self.response_times.setdefault(addr, []).append(response_time)
            if len(self.response_times[addr]) > 10:  # Limitar a 10 tempos recentes
                self.response_times[addr].pop(0)


        if cmd == MessageType.TASK_ANNOUNCE.name:
            # process project announce
            logging.debug(f"Task announce from {addr}")
            if not self.is_working and self.task_queue.empty():
                logging.info("Requesting task")
                self.network.TASK_REQUEST(addr) # type: ignore

        elif cmd == MessageType.TASK_REQUEST.name:
            # process task request
            await self._handle_task_request(message, addr)

        elif cmd == MessageType.TASK_SEND.name:
            logging.info(f"Received task from {addr}")
            await self._handle_task_send(message, addr)

        elif cmd == MessageType.CONNECT.name:
            logging.info(f"Received connect request from {addr}")
            self.network.CONNECT_REP(addr) # type: ignore

        elif cmd == MessageType.HEARTBEAT.name:
            await self._handle_heartbeat(message, addr)

        elif cmd == MessageType.TASK_CONFIRM.name:
            # confirm task
            await self._handle_task_confirm(message, addr)

        elif cmd == MessageType.CACHE_UPDATE.name:
            await self._handle_cache_update(message, addr)

        elif cmd == MessageType.PROJECT_ANNOUNCE.name:
            await self._handle_project_announce(message, addr)

        elif cmd == MessageType.RECOVERY_ELECTION.name:
            await self._handle_recovery_election(message, addr)

        elif cmd == MessageType.EVALUATION_RESPONSIBILITY_UPDATE.name:
            await self._handle_evaluation_responsibility_update(message, addr)

    # handlers
    async def _handle_task_request(self, message: dict, _addr: Tuple[str, int]):
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)

        send = False
        project_id = ""
        project_name = ""
        module = ""

        if not self.task_priority_queue.empty():
            project_id, module = await self.task_priority_queue.get()
            send = True

        elif not self.task_queue.empty():
            project_id, module = await self.task_queue.get()
            send = True

        if send:
            eval_id = None
            for e_id, e_data in self.network_cache["evaluations"].items():
                if project_id in e_data["projects"]:
                    eval_id = e_id
                    break

            project_name = self.network_cache["projects"].get(project_id, {}).get("project_name", project_id)

            # send the zip file to the node
            data = {
                "project_id": project_id,
                "module": module,
                "project_name": project_name,
                "api_port": os.environ.get("API_PORT", "5000"), # send api port to recieve results
                "eval_id": eval_id,
            }

            self.expecting_confirm[f"{project_id}::{module}"] = time.time()
            self.task_responsibilities[f"{project_id}::{module}"] = (addr, time.time()) # type: ignore
            self.network.TASK_SEND(addr, data) # type: ignore
            logging.debug(f"Sending task {project_id}::{module} to {addr}")

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

            if self.network_cache["evaluations"][e_id]["end_time"] is not None:
                # clean
                for project_id in self.network_cache["evaluations"][e_id]["projects"]:
                    if project_id in self.urls:
                        del self.urls [project_id]
                    if project_id in self.project_files:
                        del self.project_files[project_id]
                    self._remove_directory(project_id)

        for p_id, p_data in projects.items():
            if p_id not in self.network_cache["projects"]:
                self.network_cache["projects"][p_id] = {
                    "node": p_data["node"],
                    "modules": p_data["modules"],
                    "project_name": p_data["project_name"],
                }
            else:
                #merge projects
                current_modules = self.network_cache["projects"][p_id]["modules"]
                for module_name, module_data in p_data["modules"].items():
                    if module_name not in current_modules or module_data["status"] == "finished":
                        current_modules[module_name] = module_data
                    elif module_data["status"] == "running" and current_modules[module_name]["status"] == "pending":
                        current_modules[module_name]["status"] = "running"


        logging.debug(f"Cache updated from {saddr}")

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

        project_id = message["data"]["info"]["project_id"]
        project_name = message["data"]["info"]["project_name"]
        module = message["data"]["info"]["module"]
        api_port = message["data"]["info"]["api_port"]
        eval_id = message["data"]["info"].get("eval_id")
        ip = message["ip"]
        port = message["port"]
        addr = (ip, port)

        def get_file_bytes(project_id: str) -> Optional[Tuple[Any, int]]:
            import requests
            logging.debug(f"Getting file {project_id} from {addr}")
            try:
                url = f"http://{addr[0]}:{api_port}/file/{project_id}"
                response = requests.get(url, headers={"Content-Type": "application/json"})
                if response.status_code == 200:
                    if response.json()["type"] == URL:
                        # download url from github
                        url = response.json()["url"]
                        token = response.json()["token"]

                        return (url, token), URL
                    project_name = response.json().get("project_name", project_id)
                    file_b64 = response.json()["bytes"]
                    file_bytes = base64.b64decode(file_b64)
                    return (file_bytes,project_name), ZIP

                # request failed
                logging.error(f"Error getting file: {response.status_code}")
                return None
            except Exception:
                return None

        # check if folder was already downloaded
        if project_id in self.urls or project_id in self.project_files:
            self.external_task = (project_id, module)
            self._new_task((ip,api_port), project_id, module, eval_id)
            self.network.TASK_CONFIRM(addr, # type: ignore
                {"task_id": f"{project_id}::{module}"})
            if eval_id:
                self.network_cache["evaluations"].setdefault(eval_id, {"projects": [], "start_time": time.time(), "end_time": None})
                self.network_cache["evaluations"][eval_id]["projects"] = list(
                    set(self.network_cache["evaluations"][eval_id]["projects"]) | {project_id}
                )
                await self._propagate_cache()
            return

        # get file bytes
        try:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, partial(get_file_bytes, project_id))

            if res:
                info, type = res
                node_addr = f"{addr[0]}:{addr[1]}"
                if type == URL:
                    url,token = info
                    # download url from github

                    project_name = await f.download_github_repo(url, token,project_id)
                    if not project_name:
                        logging.error(f"Error downloading project {project_id} from {url}")
                        return

                    self.urls[project_id] = (url, token)


                elif type == ZIP:
                    file_bytes,project_name = info
                    await f.bytes_2_folder(file_bytes)
                    self.project_files[project_id] = base64.b64encode(file_bytes).decode('utf-8')

                self._new_project(project_id, node_addr, project_name)
                self._new_module(project_id, module)
                self.external_task = (project_id, module)
                self._new_task((ip,api_port), project_id, module, eval_id)
                self.network.PROJECT_ANNOUNCE({ # type: ignore
                    "project_id": project_id,
                    "api_port": os.environ.get("API_PORT", "5000"),
                })

                await self._propagate_cache()

                # notify node
                self.network.TASK_CONFIRM(addr, # type: ignore
                    {"task_id": f"{project_id}::{module}"})
        except Exception:
            logging.error(f"Error handling task send: {traceback.format_exc()}")

    async def _handle_task_result(self, task_id: str, info:Dict):
        """Process task result message from a worker node"""
        project_id = info["project_id"]
        module = info["module"]
        ip = info["ip"]
        port = info["port"]
        addr = (ip, port)

        # Get the current node's address
        my_addr = f"{self.outside_ip}:{self.outside_port}"
        # Obter o nó responsável atual do cache
        responsible_node = None
        responsible_node_str = None

        if project_id in self.network_cache["projects"]:
            responsible_node_str = self.network_cache["projects"][project_id].get("node")
            if responsible_node_str:
                try:
                    ip, port_str = responsible_node_str.split(":")
                    responsible_node = (ip, int(port_str))
                except Exception as e:
                    logging.warning(f"Error parsing responsible node address {responsible_node_str}: {e}")

        def update_cache(project_id:str, module:str, message:dict):
            # update project status
            self.network_cache["projects"][project_id]["modules"][module]["passed"] = message["passed"]
            self.network_cache["projects"][project_id]["modules"][module]["failed"] = message["failed"]
            self.network_cache["projects"][project_id]["modules"][module]["status"] = "finished"
            self.network_cache["projects"][project_id]["modules"][module]["time"] = message["time"]

            # update project status
            for eval_id, eval_data in self.network_cache["evaluations"].items():
                if project_id in eval_data["projects"]:
                    self.processed_evaluations.add(eval_id)
                    all_finished = all(
                        self.network_cache["projects"][p]["modules"][m]["status"] == "finished"
                        for p in eval_data["projects"]
                        for m in self.network_cache["projects"][p]["modules"]
                    )
                    if all_finished and not eval_data["end_time"]:
                        eval_data["end_time"] = time.time()

        # Check if this node is the responsible node
        is_responsible = responsible_node_str == my_addr

        # If the result is for a task this node is responsible for
        if task_id in self.task_responsibilities:
            original_addr, _ = self.task_responsibilities[task_id]

            # Se o nó responsável mudou e não é este nó, encaminhar o resultado ( "nunca" chega aqui mas é bom ter )
            if responsible_node and not is_responsible:
                if original_addr != responsible_node:
                    logging.info(f"Forwarding task result {task_id} to the new responsible node {responsible_node}")

                    url = f"http://{responsible_node[0]}:{responsible_node[1]}/task"
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        partial(self.send_http_post, url, info)
                    )

                return  # Return early to avoid processing the result locally

            # Process the result if this node is still responsible or is the new responsible node
            if is_responsible:
                # remove responsibility entry
                del self.task_responsibilities[task_id]

                update_cache(project_id, module, info)

                # inform node that successfully finished
                logging.debug(f"Received task result from {addr}")
                await self._propagate_cache()

        # If this node is the new responsible node but wasn't originally responsible
        elif is_responsible :
            logging.info(f"Received task result {task_id} as the new responsible node")

            # update project status
            if project_id in self.network_cache["projects"] and module in self.network_cache["projects"][project_id]["modules"]:

                update_cache(project_id, module, info)

                # inform node that successfully finished
                self.network.TASK_RESULT_REP(addr, {"task_id": task_id}) #type: ignore
                await self._propagate_cache()
            else:
                logging.warning(f"Received task result for unknown project/module: {task_id}")

    async def _handle_project_announce(self, message: dict, _addr: Tuple[str, int]):
        project_id = message["data"]["project_id"]
        api_port = message["data"]["api_port"]
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)
        if project_id in self.urls or project_id in self.project_files:
            return

        # request project
        try:
            import requests
            url = f"http://{addr[0]}:{api_port}/file/{project_id}"
            response = requests.get(url, headers={"Content-Type": "application/json"})
            if response.status_code == 200:
                type = response.json()["type"]
                if type == URL:
                    # dowanload url from github
                    url = response.json()["url"]
                    token = response.json()["token"]
                    if res := await f.download_github_repo(url, token,project_id):
                        self.urls[res] = (url, token)
                    self.network.PROJECT_ANNOUNCE( # type: ignore
                        {
                        "project_id": project_id,
                        "api_port": os.environ.get("API_PORT", "5000"),
                        }
                    )

                elif type == ZIP:
                    file_bytes = base64.b64decode(response.json()["bytes"])
                    await f.bytes_2_folder(file_bytes)
                    self.project_files[project_id] = response.json()["bytes"]
                    self.network.PROJECT_ANNOUNCE( # type: ignore
                        {
                        "project_id": project_id,
                        "api_port": os.environ.get("API_PORT", "5000"),
                        }
                    )
                else:
                    logging.error(f"Unknown file type: {type}")
                    return

            else:
                logging.error(f"Error getting file: {response.status_code}")
        except Exception as e:
            logging.error(f"Error getting file: {e}")

        # inform node that sucessfully finished
        logging.debug(f"Received project announce from {addr}")

    async def _handle_heartbeat(self, message: dict, _addr: Tuple[str, int]):
        # Registra o heartbeat recebido com o ID do nó
        ip = message.get("ip", None)
        port = message.get("port", None)
        addr = (ip, port)
        node_id = message.get("data", {}).get("id", f"{addr[0]}:{addr[1]}")
        self.last_heartbeat_received[node_id] = time.time()
        self.network.add_peer(node_id,addr) # type: ignore
        logging.debug(f"Heartbeat received from {ip}:{port}")

    async def check_heartbeats(self):
        "Verifica periodicamente os heartbeats para detectar falhas"
        while self.is_running:
            current_time = time.time()
            for node_id, last_time in list(self.last_heartbeat_received.items()):
                if current_time - last_time > 3 * HEARTBEAT_INTERVAL:
                    logging.warning(f"Node {node_id} is considered failed.")
                    await self.handle_node_failure(node_id)
                    del self.last_heartbeat_received[node_id]  # Remove o nó falho
                    self.network.remove_peer(node_id) # type: ignore
                    if node_id in self.network_cache["status"]:
                        del self.network_cache["status"][node_id]
            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def handle_node_failure(self, node_id: str):
        """
        Lida com a falha de um nó, elegendo um nó para receber resultados,
        Redistribuindo tarefas do nó falho"""

        logging.warning(f"Starting recovery process for failed node {node_id}")

        # 1. Verificar se há avaliações ativas no nó falho
        active_evaluations = self.get_active_evaluations_for_node(node_id)

        if active_evaluations:
            # 2. Participar da eleição para recuperação
            recovery_node = await self._elect_recovery_node(node_id, active_evaluations)

            if recovery_node == self.network.node_id: # type: ignore
                # Este nó foi eleito para recuperação
                logging.info(f"This node has been elected to retrieve node ratings {node_id}")
                await self._become_recovery_node(node_id, active_evaluations)


        # 3. Redistribuir tarefas
        tasks_to_reassign = [task_id for task_id, info in self.task_responsibilities.items()
                            if f"{info[0][0]}:{info[0][1]}" == node_id]
        for task_id in tasks_to_reassign:
            await self.add_to_priority_queue(task_id)
            del self.task_responsibilities[task_id]
            logging.info(f"Reassigned task {task_id} from failed node {node_id}")

    async def add_to_priority_queue(self, task_id: str):
        """Adiciona uma tarefa à fila de prioridade, extraindo project_id e module do task_id"""
        try:
            project_id, module = task_id.split("::")
            await self.task_priority_queue.put((project_id, module))
            logging.info(f"Task {task_id} added to priority queue")
            return True
        except Exception as e:
            logging.error(f"Error adding task to priority queue: {e}")
            return False

    # Replace the existing _elect_recovery_node method with this implementation:
    async def _elect_recovery_node(self, failed_node_id: str, active_evaluations: Dict[str, List[str]]) -> str:
        """
        Processo de eleição para determinar qual nó assumirá a responsabilidade
        de receber resultados do nó falho.

        Algoritmo: o nó com o menor ID vence a eleição.
        """
        # Initialize election tracking for this failed node
        if failed_node_id not in self.active_elections:
            self.active_elections[failed_node_id] = {}

        # Add this node as a candidate
        self.active_elections[failed_node_id][self.network.node_id] = time.time() # type: ignore

        # Announce candidacy
        election_data = {
            "candidate_id": self.network.node_id,# type: ignore
            "failed_node": failed_node_id,
            "timestamp": time.time()
        }

        self.network.RECOVERY_ELECTION(election_data) # type: ignore

        # Wait for candidates to be collected through the message handler
        election_timeout = time.time() + 2 * self.response_timeout  # 2 seconds to collect candidates
        while time.time() < election_timeout:
            await asyncio.sleep(0.1)

        # Determine the winner (node with lowest ID)
        candidates = self.active_elections.get(failed_node_id, {})

        if not candidates:
            logging.warning(f"No candidates found for failed node {failed_node_id}, assuming self as winner")
            return self.network.node_id # type: ignore

        winner = min(candidates.keys())

        logging.info(f"Election for node recovery {failed_node_id}: winner is {winner}")

        # Clean up election data
        del self.active_elections[failed_node_id]

        return winner

    async def _become_recovery_node(self, failed_node_id: str, active_evaluations: Dict[str, List[str]]):
        """
        Este nó foi eleito para ser o nó de recuperação.
        Assume a responsabilidade pelas avaliações do nó falho.
        """
        # Registrar no log quais avaliações estão sendo recuperadas
        for eval_id, projects in active_evaluations.items():
            logging.info(f"Taking responsibility for assessment {eval_id} with {len(projects)} projects")

            # Atualizar o cache para refletir que este nó agora é responsável
            for project_id in projects:
                if project_id in self.network_cache["projects"]:
                    # Atualizar o nó responsável no cache
                    node_addr = f"{self.outside_ip}:{self.outside_port}"
                    self.network_cache["projects"][project_id]["node"] = node_addr

                    # Anunciar mudança de responsabilidade
                    self.network.EVALUATION_RESPONSIBILITY_UPDATE({ # type: ignore
                        "project_id": project_id,
                        "new_node": node_addr,
                        "eval_id": eval_id
                    })

                    # Add pending/running modules to the task priority queue
                    modules_added = 0
                    for module_name, module_data in self.network_cache["projects"][project_id].get("modules", {}).items():
                        if module_data.get("status") in ["pending", "running"]:
                            # Reset status to pending to ensure it gets processed
                            self.network_cache["projects"][project_id]["modules"][module_name]["status"] = "pending"

                            # Add to priority queue
                            await self.task_priority_queue.put((project_id, module_name))
                            modules_added += 1

                    if modules_added > 0:
                        logging.info(f"Added {modules_added} modules from project {project_id} to priority queue")

        # Propagar as alterações do cache
        await self._propagate_cache()

        logging.info(f"Successfully took responsibility for evaluations from node {failed_node_id}")

    async def _handle_evaluation_responsibility_update(self, message: dict, _addr: Tuple[str, int]):
        """Processa atualizações de responsabilidade por projeto"""
        data = message.get("data", {})
        project_id = data.get("project_id")
        new_node = data.get("new_node")

        if project_id and new_node and project_id in self.network_cache["projects"]:
            # Atualizar o nó responsável no cache
            self.network_cache["projects"][project_id]["node"] = new_node
            logging.info(f"Responsibility for the project {project_id} transferred to {new_node}")

            # Atualizar tarefas em execução, se houver
            for task_id, (task_addr, timestamp) in list(self.task_responsibilities.items()):
                if task_id.startswith(f"{project_id}::"):
                    # Extrair as partes do task_id
                    _, module = task_id.split("::")

                    # Atualizar o endereço para o novo nó responsável
                    ip, port_str = new_node.split(":")
                    new_addr = (ip, int(port_str))

                    # Se este nó estiver processando uma tarefa deste projeto,
                    # deve enviar o resultado para o novo nó responsável
                    self.task_responsibilities[task_id] = (new_addr, timestamp)
                    logging.info(f"Updating result destination for task {task_id}: {new_addr}")

    async def _handle_recovery_election(self, message: dict, _addr: Tuple[str, int]):
        """Process election messages for node recovery"""
        data = message.get("data", {})
        failed_node_id = data.get("failed_node")
        candidate_id = data.get("candidate_id")
        timestamp = data.get("timestamp", time.time())

        if not failed_node_id or not candidate_id:
            logging.error(f"Invalid election message: {message}")
            return

        # Store candidate information
        if failed_node_id not in self.active_elections:
            self.active_elections[failed_node_id] = {}

        self.active_elections[failed_node_id][candidate_id] = timestamp
        logging.debug(f"Received election candidate {candidate_id} for failed node {failed_node_id}")

    async def update_response_timeout(self):
        """Atualiza o response_timeout com base nos tempos de resposta observados."""
        if time.time() - self.last_timeout_update < self.timeout_update_interval:
            return

        all_times = [t for times in self.response_times.values() for t in times]
        if not all_times:
            return  # Mantém o valor atual se não houver dados

        # Calcular média e desvio padrão
        avg_time = sum(all_times) / len(all_times)
        std_dev = (sum((t - avg_time) ** 2 for t in all_times) / len(all_times)) ** 0.5

        # Novo timeout: média + 2 vezes o desvio padrão, com limites
        new_timeout = avg_time + 2 * std_dev
        self.response_timeout = max(5.0, min(10.0, new_timeout))

        self.last_timeout_update = time.time()
        logging.debug(f"Updated response_timeout to {self.response_timeout:.2f} seconds")
