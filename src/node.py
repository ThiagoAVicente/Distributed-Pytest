"""
implements the node class
"""

import asyncio
import logging
import os
from typing import List, Dict, Any, Optional
from utils.test_runner import TestRunner
from network.NetworkFacade import NetworkFacade

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

IP:str = "0.0.0.0"

class Node:

    def __init__(self, ip:str = IP, port:int = 8000):

        self.address:tuple[str,int] = (ip, port)

        self.is_running:bool = False

        # network
        self.network_facade:Optional[NetworkFacade] = None
        self.peers: Dict[str, tuple[str, int]] = {}

        # work variables
        self.project_queue:asyncio.Queue = asyncio.Queue()

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
        logging.info(f"Node started at {self.address}")

    async def stop(self):
        "stops the node"
        self.is_running = False
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
            "status": "downloading",  #
            "processed":0,
            "urls": urls.copy() if urls else []  
        }
        
        # Start a background task to download the projects
        asyncio.create_task(self._download_projects_async(urls, token, eval_id))

        logging.info(f"eval {eval_id} submitted to node {self.address}")

        # return evaluation id
        return eval_id
        
    async def _download_projects_async(self, urls:List[str], token:str, eval_id:str):
        "downloads the projects in the background"
        for url in urls:
            project_name = await self.download_project(url, token, eval_id)

            if project_name:
                # add to queue
                await self.project_queue.put((eval_id, project_name))
                logging.info(f"Project {project_name} added to queue for evaluation {eval_id}")
            else:
                logging.error(f"Failed to download project from {url}")

        # update status
        self.evaluations[eval_id]["status"] = "ready"
        logging.info(f"All projects downloaded for evaluation {eval_id}")

    def get_evaluation_status(self, eval_id: str) -> Optional[Dict[str,Any]]:
        "return the current state of an evaluation"
        return self.evaluations.get(eval_id, None)

    def get_all_evaluations(self) -> Dict[str,Dict[str,Any]]:
        "returns all evaluations"
        return self.evaluations

    async def process_queue(self):
        " process project queue"

        while 2:
            try:
                # get the next project
                eval_id, project_name = await self.project_queue.get()
                test_runner = TestRunner(os.getcwd())

                # update eval status
                self.current_project = eval_id

                logging.info(f"Processing project {eval_id}/{project_name} at {self.address}")

                try:

                    self.evaluations[eval_id]["projects"][project_name]["status"] = "running"

                    result = await test_runner.run_tests(eval_id, project_name)
                    
                    # TODO: removewhen on distributed system
                    self.evaluations[eval_id]["processed"] += 1
                    await self.keep_clean(eval_id)
                        
                    if result:
                        #update stats
                        self.projects_processed += 1
                        self.tests_passed += result.passed
                        self.tests_failed += result.failed
                        self.modules += result.modules

                        # update eval status
                        self.evaluations[eval_id]["projects"][project_name]["status"] = "completed"
                        self.evaluations[eval_id]["projects"][project_name]["passed"] += result.passed
                        self.evaluations[eval_id]["projects"][project_name]["failed"] += result.failed
                        self.evaluations[eval_id]["projects"][project_name]["modules"] += result.modules
                    else:
                        # update eval status
                        self.evaluations[eval_id]["projects"][project_name]["status"] = "failed"
                        self.evaluations[eval_id]["projects"][project_name]["error"] = "Failed to run tests"

                except Exception as e:
                    logging.error(f"Error processing project {eval_id}/{project_name}: {e}")
                    self.evaluations[eval_id]["projects"][project_name]["status"] = "failed"
                    self.evaluations[eval_id]["projects"][project_name]["error"] = str(e)
                    
                    # TODO: removewhen on distributed system
                    self.evaluations[eval_id]["processed"] += 1
                    await self.keep_clean(eval_id)
                    
                    
                        

            except asyncio.CancelledError:
                break

            except Exception as e:
                logging.error(f"Error in project processing loop: {e}")

            await asyncio.sleep(0.1)
            
    async def keep_clean(self,eval_id:str) -> None:
        if self.evaluations[eval_id]["processed"] == \
            len(self.evaluations[eval_id]["projects"]):
            # clean up project
            await self.cleanup_project(eval_id)
            
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
                        "processed": 0,
                    }
                
                # Make sure projects is a dictionary
                if "projects" not in self.evaluations[eval_id]:
                    self.evaluations[eval_id]["projects"] = {}
                    
                # Initialize this project in the dictionary
                self.evaluations[eval_id]["projects"][project_name] = {
                    "status": "pending",
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

        if not self.network_facade or not self.network_facade.is_running():
            raise RuntimeError("Protocol not initialized. Ensure the protocol is started.")

        while self.is_running:
            try:
                message, addr = await self.network_facade.recv()

                # TODO: process message
                logging.info(f"Received message from {addr}: {message}")
                self.network_facade.HEARTBEAT(addr, status="free")

            except asyncio.CancelledError:
                break

            except Exception as e:
                logging.error(f"Error in message listening loop: {e}")

            await asyncio.sleep(0.1)
