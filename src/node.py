"""
implements the node class
"""

import asyncio
import logging
import os
import base64
import time
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

class Node:

    def __init__(self, ip:str = IP, port:int = 8000, new_network:bool = False):

        self.address:tuple[str,int] = (ip, port)
        self.is_running:bool = False
        self.is_working:bool = False

        # network
        self.network_facade:Optional[NetworkFacade] = None
        self.connected:bool = new_network
        self.last_heartbeat:float = 0

        # work variables
        self.task_queue:asyncio.Queue = asyncio.Queue()

        # stats
        self.projects_processed:int = 0
        self.tests_passed:int = 0
        self.tests_failed:int = 0
        self.modules:int = 0

        self.evaluations:Dict = {}
        self.evaluation_counter:int = 0

    async def start(self):
        "starts the node"
        self.is_running = True
        self.network_facade = NetworkFacade(self.address)
        await self.network_facade.start()
        if self.connected:
            await self.network_facade.start_discovery()
        logging.info(f"Node started at {self.address}")

    async def stop(self):
        "stops the node"
        self.is_running = False
        if self.network_facade:
            await self.network_facade.stop()
        logging.info(f"Node stopped at {self.address}")

    def get_status(self) -> Dict[str, Any]:
        "returns the status of the node"
        res:dict = {
            "address": f"{self.address[0]}:{self.address[1]}" ,
            "failed": self.tests_failed,
            "passed": self.tests_passed,
            "projects": self.projects_processed,
            "modules":self.modules,
            "evaluations": list(self.evaluations.keys()),
        }
        return res

    async def submit_evalution_url(self, urls:list[str] = None , token:str = None) -> str:
        "submits a eval to the node"
        self.evaluation_counter += 1
        eval_id = str(self.evaluation_counter)

        self.evaluations[eval_id] = {
            "id": eval_id,
            "projects": {},
            "processed":0,
            "urls": urls.copy() if urls else []
        }

        if not (urls and token):
            logging.error("No urls or token provided")
            return None

        # Start a background task to download the projects
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
        eval_id = info["eval_id"]

        if type == URL:
            token = info["token"]
            urls = info["urls"]
            projects = {}

            for url in urls:
                project_name = await self.download_project(url, token, eval_id)
                if project_name:
                    projects[project_name] = []
                # get modules per project
                for project_name in projects.keys():
                    # logging.debug(f"Project {project_name} downloaded")

                    test_runner = PytestRunner(os.getcwd())
                    modules = await test_runner.get_modules(eval_id,project_name)

                    if modules:
                        projects[project_name] = modules

                        # add to task queue
                        for module in modules:
                            await self.task_queue.put((eval_id,project_name, module))

    ## TODO: refactor
    async def _download_projects_async(self, urls:List[str], token:str, eval_id:str) -> str:
        "downloads the projects in the background"
        for url in urls:
            project_name = await self.download_project(url, token, eval_id)

            if project_name:
                return project_name

        return None

    def get_evaluation_status(self, eval_id: str) -> Optional[Dict[str,Any]]:
        "return the current state of an evaluation"
        return self.evaluations.get(eval_id, None)

    def get_all_evaluations(self) -> Dict[str,Dict[str,Any]]:
        "returns all evaluations"
        return self.evaluations

    async def process_queue(self):
        " process task queue"

        logging.debug("Node started processing queue")

        while self.is_running:
            try:
                # get the next project
                eval_id, project_name, module = await asyncio.wait_for(self.task_queue.get(), timeout=1)
                self.is_working = True
                test_runner = PytestRunner(os.getcwd())
                logging.debug(f"Processing {eval_id}::{project_name}::{module}")


                result = await test_runner.run_tests(eval_id, project_name, module)
                if result:
                    # update stats
                    self.tests_passed += result.passed
                    self.tests_failed += result.failed
                    self.modules += 1

                    # update evaluation status
                    if eval_id in self.evaluations:
                        self.evaluations[eval_id]["projects"][project_name]["passed"] += result.passed
                        self.evaluations[eval_id]["projects"][project_name]["failed"] += result.failed
                        self.evaluations[eval_id]["projects"][project_name]["modules"] += 1


                else:
                    logging.error(f"Error processing {eval_id}::{project_name}::{module}")

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


    async def download_project(self, url:str, token:str = None, eval_id:str = "downloaded") -> Optional[str]:
        "downloads the project from the given url"
        try:
            if url.startswith("https://github.com") :
                from utils.functions import download_github_repo
                res:Optional[str] =  await download_github_repo(url, token, eval_id)

                if not res:
                    return None

                 # Extract just the project name (base name) from the path
                project_name = os.path.basename(res)

                # Initialize the evaluation if it doesn't exist
                if eval_id not in self.evaluations:
                    self.evaluations[eval_id] = {
                        "id": eval_id,
                        "projects": {},
                    }

                # Make sure projects is a dictionary
                if "projects" not in self.evaluations[eval_id]:
                    self.evaluations[eval_id]["projects"] = {}

                # Initialize this project in the dictionary
                self.evaluations[eval_id]["projects"][project_name] = {
                    "passed": 0,
                    "failed": 0,
                    "modules": 0,
                            }

                return project_name

            else:
                logging.error(f"Unsupported url: {url}")
                return None

        except Exception as e:
            logging.error(f"Error downloading project: {e}")
            return None

    async def cleanup_project(self,eval_id:str):
        " remove project dir "
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._remove_directory, eval_id)
        except Exception as e:
            logging.error(f"Error cleaning up project: {e}")
            return False

    def _remove_directory(self, path: str):
            """Remove a directory and all its contents"""
            import shutil
            shutil.rmtree(path, ignore_errors=True)

    async def listen(self):
        "main loop for message listening"
        logging.debug("Node started listening")
        if not self.network_facade or not self.network_facade.is_running():
            raise RuntimeError("Protocol not initialized. Ensure the protocol is started.")

        if not self.connected:
            # stop coroutine till connected
            try:
                await asyncio.wait_for( self.network_facade.connect(), timeout= 5 )
                self.connected = True
                logging.info("Connected to a network")

            except asyncio.TimeoutError:
                logging.error("Connection timed out.")
                await self.stop()

        # start listening for messages
        logging.debug("Node started listening for messages")
        while self.is_running:
            await asyncio.sleep(0.1)

            try:
                message, addr = await asyncio.wait_for(self.network_facade.recv(),timeout =1)

                cmd = message.get("cmd")

                if cmd == MessageType.TASK_ANNOUNCE.name:
                    # process project announce
                    logging.debug(f"Project announce from {addr}: {message}")
                    if not self.is_working:
                        self.network_facade.TASK_REQUEST(addr)

                elif cmd == MessageType.TASK_REQUEST.name:
                    # process task request
                    logging.debug(f"Task request from {addr}: {message}")
                    if not self.task_queue.empty():
                        eval_id, project_name, module = await self.task_queue.get()
                        file_bytes:bytes = await f.folder_2_bytes(os.path.join(os.getcwd(),str(eval_id), project_name))
                        file_b64 = base64.b64encode(file_bytes).decode('utf-8')
                        logging.debug(f"ZIP file size: {len(file_bytes)} bytes, base64 size: {len(file_b64)} bytes")
                        data = {
                            
                            "eval_id": eval_id,
                            "project_name": project_name,
                            "module": module,
                            "file": file_b64,
                        }
                        self.network_facade.TASK_SEND(addr,data)
                        logging.debug(f"Sending task {eval_id}::{project_name}::{module} to {addr}")

                elif cmd == MessageType.TASK_SEND.name:
                    logging.info(f"Received task from {addr}")


                    # create folder
                    eval_id = message["data"]["info"]["eval_id"]
                    project_name = message["data"]["info"]["project_name"]
                    module = message["data"]["info"]["module"]

                    file_b64 = message["data"]["info"]["file"]
                    file_bytes = base64.b64decode(file_b64)
                    
                    
                    res = await f.bytes_2_folder(file_bytes, os.path.join(os.getcwd(),str(eval_id), project_name))

                    if res:

                        # put tast in queue
                        if eval_id not in self.evaluations:
                            self.evaluations[eval_id] = {
                                "id": eval_id,
                                "projects": {},
                            }
                            self.evaluations[eval_id]["projects"][project_name] = {
                                "passed": 0,
                                "failed": 0,
                                "modules": 0,
                            }

                        await self.task_queue.put((eval_id, project_name, module))
                            
                elif cmd == MessageType.HEARTBEAT.name:
                    logging.info(f"Received heartbeat from {addr}")

            except asyncio.CancelledError:
                break
            except asyncio.TimeoutError:
                pass

            except Exception as e:
                logging.error(f"Error in message listening loop: {e}")

            # heartbeat
            if time.time() - self.last_heartbeat > 5:
                # send heartbeat
                self.network_facade.HEARTBEAT()
                logging.debug("Sending heartbeat ")
                self.last_heartbeat = time.time()

            # anounce project
            if not self.task_queue.empty():
                self.network_facade.TASK_ANNOUNCE()

        logging.debug("Node stopped listening")
        return
