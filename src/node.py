"""
implements the node class
"""
import shutil
import asyncio
import logging
import zipfile
import os
import traceback
import time

from typing import List, Dict, Any, Optional, Set, Tuple
from network.message import MessageType
from utils.test_runner import PytestRunner
from network.Network import Network
import utils.functions as f
from managers.CacheManager import CacheManager
from managers.TaskManager import TaskManager

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logging.getLogger().setLevel(logging.DEBUG)

IP:str = "0.0.0.0"
URL:int = 1
ZIP:int = 0
HEARTBEAT_INTERVAL:float = 7
UPDATE_INTERVAL:float = 5
TASK_ANNOUNCE_INTERVAL:float = 3

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

        # network
        self.network:Optional[Network] = None

        # time variables
        self.last_heartbeat:float = .0
        self.last_task_announce:float = .0
        self.last_update:float = .0
        self.last_clean_up:float = .0
        self.last_dead_check:float = .0

        # stats
        self.tests_passed:int = 0
        self.tests_failed:int = 0
        self.modules:int = 0

        self.evaluation_counter:int = 0
        self.submitted_evaluations:Set = set()  # set of evaluation ids that were submitted

        # cache manager
        self.cache_manager: CacheManager = CacheManager(self)

        # task manager
        self.task_manager: TaskManager = TaskManager(self)

        # Adicionado para tolerância a falhas
        self.last_heartbeat_received: Dict[str, float] = {}         # Rastreia o último heartbeat por nó
        self.response_times: Dict[tuple[Any,Any], List[float]] = {}     # Tempos de resposta por nó (addr: lista de tempos)
        self.response_timeout: float = 5.0                          # Valor inicial do timeout
        self.timeout_update_interval: float = 10.0                  # Intervalo para atualizar o timeout
        self.last_timeout_update: float = time.time()               # Última atualização do timeout

        # Election tracking
        self.active_elections: Dict[str, List[str]] = {}  # failed_node_id -> {candidate_id: timestamp}
        self.failed_nodes: Dict[str,str] = {}
        self.election_data:Dict[str,Dict[str, List[str]]] = {}

    async def start(self):
        "starts the node"

        # start network
        self.network = Network(self.address,self.connected)
        await self.network.start()

        self.is_running = True

        # start cache manager
        await self.cache_manager.start()

        # start task manager
        await self.task_manager.start()

        # start node tasks
        self.running_tasks = [
            asyncio.create_task(self.check_heartbeats()),
            asyncio.create_task(self.listen()),
            asyncio.create_task(self.preriodic_heartbeats(HEARTBEAT_INTERVAL/2))
        ]

        asyncio.gather(*self.running_tasks)

        logging.info(f"Node started at {self.outside_ip}:{self.outside_port}")

    async def preriodic_heartbeats(self, interval:float = HEARTBEAT_INTERVAL):
        "sends periodic heartbeats to the network"
        while self.is_running:
            try:
                self.heartbeat()
                logging.debug("Sent periodic heartbeat")
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"Error in periodic heartbeat: {e}")
                await asyncio.sleep(1)

    async def stop(self):
        "stops the node"
        self.is_running = False

        # stop all node tasks
        for task in self.running_tasks:
            if not task.done():
                task.cancel()

        # stop task manager
        await self.task_manager.stop()

        # stop cache manager
        await self.cache_manager.stop()

        # stop network
        if self.network:
            await self.network.stop()

        logging.info("Node stopped")

    def _get_status(self)-> Dict[str, Any]:
        res:Dict = {
            "failed": self.tests_failed,
            "passed": self.tests_passed,
            "projects": len(self.task_manager.get_processed_projects()),
            "modules": self.modules,
            "evaluations": list(self.task_manager.get_processed_evaluations()),
            "submitted_evaluation":list(self.submitted_evaluations)
        }
        return res

    def get_network_schema(self) -> Dict[str, List[str]]:
        "returns the network schema"
        return self.cache_manager.get_network_schema(self.network.get_peers_ip())

    def get_status(self) -> Dict[str, Any]:
        "returns the status of the node"

        def sum_status() -> Dict[str, Any]:
            "sums the status of all nodes"

            res:Dict[str,int] = {
                "failed": 0,
                "passed": 0,
                "projects": 0,
                "evaluations": 0,
            }

            project_count:int = 0

            # for each project
            projects_cache = self.cache_manager.get_projects_cache()
            evaluations_cache = self.cache_manager.get_evaluations_cache()

            for project_id, project_data in projects_cache.items():
                project_count += 1

                # for each module in projecet
                for module_stats in project_data["modules"].values():
                    res["passed"] += module_stats["passed"]
                    res["failed"] += module_stats["failed"]

            res["projects"] = project_count
            res["evaluations"] = len(evaluations_cache.keys())

            return res

        res = {"all":{},"nodes":[]}

        # Update current node status in cache
        self.cache_manager.update_node_status(
            f"{self.outside_ip}:{self.outside_port}",
            self.network.get_peers_ip(), # type: ignore
            self._get_status()
        )

        stats = self.cache_manager.get_status_cache()

        res["nodes"] = [
            {"address": node, **{k: v for k, v in data["stats"].items() if k != "submitted_evaluation"}}
            for node, data in stats.items()
        ]
        res["nodes"].append
        res["all"] = sum_status()

        return res

    def _new_evaluation(self,eval_id:str):
        "creates a new evaluation entry"
        self.submitted_evaluations.add(eval_id)
        self.cache_manager.create_evaluation(eval_id)

    def _new_project(self, project_id:str, node_addr: str, project_name:str):
        self.cache_manager.create_project(project_id, node_addr, project_name)

    def _new_module(self,project_id:str, module_name:str):
        self.cache_manager.create_module(project_id, module_name)

    def _new_task(self,addr:Tuple[str,int],project_id:str, module_name:str, eval_id: Optional[str] = None):
        """creates a new task entry"""
        self.task_manager.create_task(addr, project_id, module_name, eval_id)

    async def submit_evaluation(self, folder_name:str,zip_file_name:str) -> Optional[str]:

        if not os.path.isdir(folder_name):
            logging.error(f"Folder {folder_name} does not exist")
            return None

        # get evaluation id
        self.evaluation_counter += 1
        eval_id = f"{self.network.node_id}{self.evaluation_counter}" #type: ignore

        self._new_evaluation(eval_id)

        asyncio.create_task(self.add_zip_projects(folder_name,zip_file_name, eval_id))

        return eval_id

    async def add_zip_projects(self, folder_name:str, zip_file_name:str,eval_id: str):
        """
        assuming that all projects are already downloaded and unzipped,
        this function retrieves their tasks and adds them to the task queue
        :folder_name - name of the folder containing the projects
        :eval_id - evaluation id to add the projects to
        """

        zip_path = os.path.join(folder_name, zip_file_name)
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(folder_name)

        # remove .zip
        os.remove(zip_path)

        project_ids:List[str] = []
        node_addr = f"{self.outside_ip}:{self.outside_port}"

        # iterate though each project in the folder and move it to the current directory
        # change the project_name to the project_id
        for project_name in os.listdir(folder_name):
            abs_path = os.path.join(folder_name, project_name)

            # skip if its not a directory
            if not os.path.isdir(abs_path):
                continue

            # create project id
            project_id = str(time.time()) + self.network.node_id #type: ignore

            # move the project to the current directory with project_id as the name
            shutil.move(abs_path, os.path.join(os.getcwd(), project_id))

            self._new_project(project_id, node_addr, project_name)
            project_ids.append(project_id)


            self.network.project_announce( # type: ignore
                {
                "project_id": project_id,
                "api_port": os.environ.get("API_PORT", "5000"),
                "project_name": project_name,
                "eval_id": eval_id,
                "url": None,
                "token": None,
                "type": ZIP
                }
            )
            self.cache_manager.add_project_to_evaluation(eval_id, project_id)

        await self._propagate_cache()
        await self.retrieve_tasks("regular", project_ids)
        await self._propagate_cache()

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
        asyncio.create_task(self.add_github_projects(urls=urls,token=token, eval_id=eval_id))

        return eval_id

    async def add_github_projects(self, urls: List[str], token: str, eval_id: str) -> None:
        """
        downlaods a list of github projects calls the function to retrive their tasks
        :urls - list of urls to download
        :token - github token to use for downloading
        :eval_id - evaluation id to add the projects to
        """

        project_ids:List[str] = []
        for url in urls:
            project = await self.download_project(url, token, eval_id)
            if project:
                project_id, project_name = project
                project_ids.append(project_id)

                # add project to cache
                self.cache_manager.add_project_to_evaluation(eval_id, project_id)
                self._new_project(project_id, f"{self.outside_ip}:{self.outside_port}", project_name)

            await asyncio.sleep(0.01)

        # propagate cache
        await self._propagate_cache()

        # get all tasks from projects
        await self.retrieve_tasks("regular", project_ids)

        await self._propagate_cache()

    async def retrieve_tasks(self, queue_type:str, projects:List[str])-> None:
        """
        retrive tasks (pytest modules) from a project
        ASSUMES THAT THE PROJECTS ARE ALREADY DOWNLOADED AND UNZIPPED
        :projects - list of projects to retrieve tasks from
        :queue_type - "regular" or "priority" to specify which queue to use
        """

        async def add_module(project_id,module):

            projects_cache = self.cache_manager.get_projects_cache()
            if module in projects_cache[project_id]["modules"] and projects_cache[project_id]["modules"][module]["status"] == "finished":
                return

            self._new_module(project_id, module)

            if queue_type == "priority":
                await self.task_manager.add_task_to_priority_queue(f"{project_id}::{module}")
            else:
                await self.task_manager.add_task_to_queue(project_id, module)

        tasks_found:List[Tuple[str,str]]  = [] # list of tasks found in the projects
        test_runner = PytestRunner(os.getcwd())

        # get modules from each project
        for project_id in projects:
            modules = await test_runner.get_modules(project_id)

            if modules:
                # add new tasks to the list
                tasks_found += [(project_id, module) for module in modules]

        # Add each task to the queue
        for task in tasks_found:
            project_id, module_name = task
            await add_module(project_id, module_name)

    def get_evaluation_status(self, eval_id: str) -> Optional[Dict[str,Any]]:
        "return the current state of an evaluation"
        return self.cache_manager.get_evaluation_status(eval_id)

    def get_all_evaluations(self) -> List[str]:
        "returns all evaluations"
        return self.cache_manager.get_all_evaluations()

    def heartbeat(self):
        self.last_heartbeat = time.time()
        self.network.heartbeat({
            "id": self.network.node_id, # type: ignore"
            "peers": self.network.get_peers()
        })



    def send_http_post(self,url:str,info:dict):
        "sends a post request to the given url with the given info"
        try:
            import requests
            headers = {'Content-Type': 'application/json'}
            response = requests.post(url, json=info, headers=headers)
            if response.status_code == 200:
                return response.json()
            else:
                logging.error(f"Error sending post request: {response.status_code} with response {response.text}")
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
                self.network.project_announce( # type: ignore
                    {
                    "project_id": project_id,
                    "api_port": os.environ.get("API_PORT", "5000"),
                    "project_name": project_name,
                    "eval_id": eval_id,
                    "url": url,
                    "token": token,
                    "type": URL
                    }

                )
                self.cache_manager.add_project_to_evaluation(eval_id, project_id)
                await self._propagate_cache()

                return project_id,  project_name

            else:
                logging.error(f"Unsupported url: {url}")
                return None

        except Exception as e:
            logging.error(f"Error downloading project: {e}")
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

        # If we still don't have an address but have peers, try to find it there
        node_addr = self.failed_nodes[node_id]
        logging.info(f"Found address {node_addr} for node {node_id} in peers")

        status_cache = self.cache_manager.get_status_cache()
        eval_ids = status_cache[node_addr]["stats"]["submitted_evaluation"]
        found_projects = set()

        for eval_id in eval_ids:
            # reset found projects for each evaluation
            found_projects.clear()

            evaluations_cache = self.cache_manager.get_evaluations_cache()
            projects_cache = self.cache_manager.get_projects_cache()

            if eval_id not in evaluations_cache:
                logging.warning(f"Evaluation {eval_id} not found in cache")
                continue

            for project_id in evaluations_cache[eval_id]["projects"]:
                # check if the project was already processed by going though the modules status
                for module_data in projects_cache[project_id]["modules"].values():
                    if module_data.get("status") in ["pending", "running"]:
                        found_projects.add(project_id)
                        break

            active_evaluations[eval_id] = list(found_projects)


        if active_evaluations:
            logging.info(f"Found active projects for node {node_id}: {active_evaluations}")
        else:
            logging.warning(f"No active projects found for node {node_id}")

        return active_evaluations

    async def listen(self):
        "main loop for message listening"
        logging.debug("Node started listening")

        if not self.network or not self.network.is_running():
            raise RuntimeError("Protocol not initialized. Ensure the protocol is started.")

        if not self.connected:
            await self.connect()
            self.last_heartbeat = time.time()
            self.last_clean_up = time.time()

        # start listening for messages
        logging.debug("Node started listening for messages")
        while self.is_running:

            current_time = time.time()

            # Atualizar o timeout dinamico
            await self.update_response_timeout()

            # Clean up expired confirmations using TaskManager method
            await self.task_manager.cleanup_expired_confirmations(self.response_timeout)

            if current_time - self.last_clean_up > 20:
                await self._make_clean()

            if current_time - self.last_update > UPDATE_INTERVAL:
                await self._propagate_cache()

            # anounce task
            has_task:bool = (self.task_manager.get_queue_size() > 0 or self.task_manager.get_priority_queue_size() > 0)
            if  has_task and current_time - self.last_task_announce > TASK_ANNOUNCE_INTERVAL:
                self.network.task_announce()
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
        node_cache = self.cache_manager.prepare_cache_for_propagation(
            self.outside_ip,
            self.outside_port,
            self.network.get_peers_ip(), # type: ignore
            self._get_status()
        )
        self.network.cache_update(node_cache) # type: ignore
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
            if not self.is_working and self.task_manager.get_queue_size() == 0:
                logging.info("Requesting task")
                self.network.task_request(addr) # type: ignore

        elif cmd == MessageType.TASK_REQUEST.name:
            # process task request
            await self._handle_task_request(message, addr)

        elif cmd == MessageType.TASK_SEND.name:
            logging.info(f"Received task from {addr}")
            await self._handle_task_send(message, addr)

        elif cmd == MessageType.CONNECT.name:
            logging.info(f"Received connect request from {addr}")
            id = self.network.CONNECT_REP(addr) # type: ignore
            self.last_heartbeat_received[id] = time.time()

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

        elif cmd == MessageType.RECOVERY_ELECTION_REP.name:
            await self._handle_recovery_election_rep(message)

        elif cmd == MessageType.RECOVERY_ELECTION_RESULT.name:
            await self._handle_recovery_election_result(message)

    async def _make_clean(self):
        """remove all project files from evaluations that were already processed"""

        evaluations_cache = self.cache_manager.get_evaluations_cache()
        for e_id in evaluations_cache.keys():
            if evaluations_cache[e_id]["end_time"] is not None:
                # clean
                for project_id in evaluations_cache[e_id]["projects"]:
                    if project_id in self.urls:
                        del self.urls [project_id]
                    f.remove_directory(project_id)

    # handlers
    async def _handle_recovery_election_result(self,message):
        """
        Handles the result of a recovery election.
        Updates the election data with the winning node's projects.
        """
        data = message["data"]
        evaluations = data["evaluations"]
        failed_node_id = data["failed_node_id"]

        await self._become_recovery_node(failed_node_id, evaluations)

    async def _handle_recovery_election_rep(self,message):

        data = message["data"] # contains the evaluatiopns: projects
        node_id = data["node_id"]
        failed_node_id = data["failed_node_id"]
        election_data = data["evaluations"]

        if failed_node_id not in self.active_elections:
            return

        self.active_elections[failed_node_id].append(node_id)

        for eval_id, projects in election_data.items():
            if eval_id not in self.election_data:
                self.election_data[eval_id] = {"projects": projects, "nodes": []}
            else:
                self.election_data[eval_id]["projects"].extend(projects)

    async def _handle_task_request(self, message: dict, addr: Tuple[str, int]):
        await self.task_manager.handle_task_request(message, addr)

    async def _handle_cache_update(self, message: dict, addr: Tuple[str, int]):

        saddr = message["data"]["addr"]
        self.cache_manager.merge_cache_update(saddr, message["data"])
        logging.debug(f"Cache updated from {saddr}")

    async def _handle_task_confirm(self, message: dict, addr: Tuple[str, int]):
        await self.task_manager.handle_task_confirm(message, addr)

    async def request_project(self,message:Dict) -> Optional[Tuple[str, str]]:
        """
        Request project from the node
        :info: dict with project info
        :return: tuple of project_id and project_name
        """
        ip = message["ip"]
        port = message["port"]
        addr = (ip, port)
        info = message["data"]

        url = info.get("url", None)
        token = info.get("token", None)
        project_id = info["project_id"]
        api_port = info["api_port"]
        type = info["type"]
        project_name = info["project_name"]

        if type == URL:
            # download project from github
            project = await f.download_github_repo(url, token, os.path.join(os.getcwd(), project_id))
            if project:
                return project_id, project_name

        elif type == ZIP:
            url  = f"http://{addr[0]}:{api_port}/file/{project_id}"
            loop = asyncio.get_running_loop()
            filename = await loop.run_in_executor(None, f.download_zip, url)
            if filename:
                await loop.run_in_executor(None, f.extract_zip_to_current_dir, filename)
                os.remove(filename)
                return project_id, project_name

        logging.error(f"Failed to request project from {addr}")
        return None

    async def _handle_task_send(self, message: dict, addr: Tuple[str, int]):
        await self.task_manager.handle_task_send(message, addr)

    async def _handle_task_result(self, task_id: str, info:Dict):
        """Process task result message from a worker node"""
        return await self.task_manager.handle_task_result(task_id, info)

    async def _handle_project_announce(self, message: dict, addr: Tuple[str, int]):

        logging.debug("Received project announce")

        project_id = message["data"]["project_id"]

        if project_id in self.urls :
            return

        await self.request_project(message)

    async def _handle_heartbeat(self, message: dict, addr: Tuple[str, int]):
        # Registra o heartbeat recebido com o ID do nó
        node_id =message["data"]["id"]
        peers = message["data"]["peers"]

        self.last_heartbeat_received[node_id] = time.time()

        if node_id in self.failed_nodes:
            del self.failed_nodes[node_id]
            logging.info(f"Node {node_id} has recovered and is back online")

        self.network.add_peer(node_id,addr) # type: ignore

        excluded_nodes = set(self.active_elections.keys()).union(set(self.failed_nodes.keys()))
        self.network.merge_peers(peers, excluded_nodes) # type: ignore

        logging.debug(f"Heartbeat received from {addr[0]}:{addr[1]}")

    async def check_heartbeats(self):
        "Verifica periodicamente os heartbeats para detectar falhas"
        while self.is_running:
            current_time = time.time()
            for node_id, last_time in list(self.last_heartbeat_received.items()):
                if current_time - last_time > 3 * HEARTBEAT_INTERVAL:

                    del self.last_heartbeat_received[node_id]  # Remove o nó falho
                    if node_id not in self.network.peers:  # type: ignore
                        continue

                    addr = self.network.peers[node_id]   #type: ignore
                    addr_str = f"{addr[0]}:{addr[1]}"
                    await self.reassign(addr_str)

                    logging.warning(f"Node {node_id} is considered failed.")
                    self.network.remove_peer(node_id) # type: ignore

                    self.failed_nodes[node_id] = addr_str # add new failed node
                    await self.handle_node_failure(node_id)

                    self.cache_manager.del_node_status(addr_str)

            await asyncio.sleep(HEARTBEAT_INTERVAL)

    async def handle_node_failure(self, node_id: str):
        """
        Lida com a falha de um nó, elegendo um nó para receber resultados,
        Redistribuindo tarefas do nó falho"""

        logging.warning(f"Starting recovery process for failed node {node_id}")

        # check if there is a need to do a election
        active_evaluations = self.get_active_evaluations_for_node(node_id)

        if active_evaluations:
            # 2. Participar da eleição para recuperação
            recovery_node, evaluations = await self._elect_recovery_node(node_id)

            if recovery_node == self.network.node_id: # type: ignore
                # Este nó foi eleito para recuperação
                logging.info(f"This node has been elected to retrieve node ratings {node_id}")
                await self._become_recovery_node(node_id, evaluations)

            else:
                addr = self.network.peers.get(recovery_node) # type: ignore
                if addr:
                    logging.info(f"Node {recovery_node} has been elected to retrieve node ratings {node_id}")
                    # Enviar dados de avaliações ativas para o nó eleito
                    data = {"evaluations": evaluations,"failed_node_id":node_id}
                    self.network.recovery_election_result(addr, data)

    async def reassign(self,node_saddr:str):
        await self.task_manager.reassign_tasks(node_saddr)

    # Replace the existing _elect_recovery_node method with this implementation:
    async def _elect_recovery_node(self, failed_node_id: str):
        """
        Processo de eleição para determinar qual nó assumirá a responsabilidade
        de receber resultados do nó falho.

        Algoritmo: o nó com o menor ID vence a eleição.
        """
        # Initialize election tracking for this failed node
        if failed_node_id not in self.active_elections:
            self.active_elections[failed_node_id] = []

        # Add this node as a candidate
        self.active_elections[failed_node_id] = [self.network.node_id] # type: ignore
        self.election_data[failed_node_id]=self.get_active_evaluations_for_node(failed_node_id)

        # Announce candidacy
        election_data = {
            "candidate_id": self.network.node_id,# type: ignore
            "failed_node": failed_node_id,
            "timestamp": time.time(),
            "extra":self.election_data[failed_node_id], # add info to merge after,
            "failed_node_addr": self.failed_nodes.get(failed_node_id, None)
        }

        self.network.recovery_election(election_data) # type: ignore

        # Wait for candidates to be collected through the message handler
        election_timeout = time.time() + 2 * self.response_timeout  # 2 seconds to collect candidates
        while time.time() < election_timeout:
            await asyncio.sleep(0.01)

        # Determine the winner (node with lowest ID)
        candidates = self.active_elections[failed_node_id]

        # Clean up election data
        del self.active_elections[failed_node_id]

        winner = min(candidates)

        logging.info(f"Election for node recovery {failed_node_id}: winner is {winner}")

        return winner, self.election_data[failed_node_id]

    async def _become_recovery_node(self, failed_node_id: str, active_evaluations: Dict[str, List[str]]):
        """
        Este nó foi eleito para ser o nó de recuperação.
        Assume a responsabilidade pelas avaliações do nó falho.
        """
        # Registrar no log quais avaliações estão sendo recuperadas
        projects_id = []
        for eval_id, projects in active_evaluations.items():
            logging.info(f"Taking responsibility for assessment {eval_id} with {len(projects)} projects")

            # Atualizar o cache para refletir que este nó agora é responsável
            for project_id in projects:
                # Atualizar o nó responsável no cache
                node_addr = f"{self.outside_ip}:{self.outside_port}"
                projects_cache = self.cache_manager.get_projects_cache()
                projects_cache[project_id]["node"] = node_addr
                projects_id.append(project_id)
                # Anunciar mudança de responsabilidade
                self.network.evaluation_responsibility_update({ # type: ignore
                    "project_id": project_id,
                    "new_node": node_addr,
                })

        asyncio.create_task(self.retrieve_tasks("priority",projects_id))

        # Propagar as alterações do cache
        await self._propagate_cache()

        logging.info(f"Successfully took responsibility for evaluations from node {failed_node_id}")

    async def _handle_evaluation_responsibility_update(self, message: dict, addr: Tuple[str, int]):
        """Processa atualizações de responsibilidade por projeto"""
        data = message.get("data", {})
        project_id = data.get("project_id")
        new_node = data.get("new_node")

        projects_cache = self.cache_manager.get_projects_cache()
        if project_id and new_node and project_id in projects_cache:
            # Atualizar o nó responsável no cache
            if projects_cache[project_id]["node"] != new_node:
                projects_cache[project_id]["node"] = new_node
                logging.info(f"Responsibility for the project {project_id} transferred to {new_node}")
                self.network.evaluation_responsibility_update({ # type: ignore
                    "project_id": project_id,
                    "new_node": new_node,
                })

    async def _handle_recovery_election(self, message: dict, addr: Tuple[str, int]):
        """Process election messages for node recovery"""
        data = message.get("data", {})
        failed_node_id = data.get("failed_node")
        candidate_id = data.get("candidate_id")
        timestamp = data.get("timestamp", time.time())
        failed_node_addr = data.get("failed_node_addr", None)

        if not failed_node_id or not candidate_id:
            logging.error(f"Invalid election message: {message}")
            return

        # Store candidate information
        if failed_node_id not in self.active_elections:
            self.active_elections[failed_node_id] = {}

        self.active_elections[failed_node_id][candidate_id] = timestamp

        self.failed_nodes[failed_node_id] = failed_node_addr

        if failed_node_id in self.network.peers: # type: ignore
            logging.warning(f"Node {failed_node_id} is considered failed.")
            self.network.remove_peer(failed_node_id) # type: ignore


        election_data_temp = message["data"]["extra"]  # get active evaluations
        evaluations = self.get_active_evaluations_for_node(failed_node_id)
        for eval_id, projects in election_data_temp.items():
            if eval_id not in evaluations:
                evaluations[eval_id] = projects
            else:
                evaluations[eval_id].extend(projects)

        self.cache_manager.del_node_status(failed_node_addr)

        to_send = {
            "failed_node_id": failed_node_id,
            "evaluations": evaluations,
            "node_id": self.network.node_id,  # type: ignore
        }
        self.network.recovery_election_rep(addr,to_send)

        await self.reassign(f"{failed_node_addr[0]}:{failed_node_addr[1]}")
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
