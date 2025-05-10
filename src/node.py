"""
implements the node class
"""

import asyncio
import logging
import os
import uuid
from typing import List, Dict, Any, Optional
from protocol import AsyncProtocol

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

IP:str = "127.0.0.1"

class Node:

    def __init__(self, ip:str = IP, port:int = 8000):

        self.address:tuple[str,int] = (ip, port)

        self.is_running:bool = False

        # network
        self.protocol: Optional[AsyncProtocol] = None
        self.peers: Dict[str, tuple[str, int]] = {}

        # work variables
        self.project_queue:asyncio.Queue = asyncio.Queue()

        # stats
        self.projects_processed:int = 0
        self.tests_passed:int = 0
        self.tests_failed:int = 0

        self.evaluations:Dict = {}
        self.evaluation_counter:int = 0

    async def start(self):
        "starts the node"
        self.is_running = True
        self.protocol = await AsyncProtocol.create(self.address)
        logging.info(f"Node started at {self.address}")

    async def stop(self):
        "stops the node"
        self.is_running = False
        logging.info(f"Node stopped at {self.address}")

    def get_status(self) -> Dict[str, Any]:
        "returns the status of the node"
        return {
            "address": self.address,
            "projects_processed": self.projects_processed,
            "tests_passed": self.tests_passed,
            "tests_failed": self.tests_failed
        }

    async def submit_evalution(self, url:str, token:str = None) -> str:
        "submits a eval to the node"
        eval_id = str(uuid.uuid4())
        await self.project_queue.put((eval_id, url, token))
        logging.info(f"eval {eval_id} submitted to node {self.address}")

        # TODO: change this
        eval_info = {
            "id": eval_id,
            "url": url,
            "token": token,
            "status": "pending",
        }

        self.evaluations[eval_id] = eval_info

        # return evaluation id
        return eval_id

    def get_evaluation_status(self, eval_id: str) -> Optional[Dict[str,Any]]:
        "return the current state of an evaluation"
        return self.evaluations.get(eval_id, None)

    def get_all_evaluations(self) -> Dict[str,Dict[str,Any]]:
        "returns all evaluations"
        return self.evaluations

    async def process_queue(self):
        " process project queue"

        from utils.test_runner import TestRunner

        while 2:
            try:
                # get the next project
                eval_id, url, token = await self.project_queue.get()
                test_runner = TestRunner(os.getcwd())

                # update eval status
                self.evaluations[eval_id]["status"] = "downloading"

                self.current_project = eval_id

                logging.info(f"Processing project {eval_id} at {self.address}")

                try:
                    # dowanlaod proweject
                    res:bool = await self.download_project(url, token, eval_id)

                    if not res:
                        logging.error(f"Failed to download project {eval_id}")
                        self.evaluations[eval_id]["status"] = "failed"
                        self.evaluations[eval_id]["error"] = "Failed to download project"
                        continue

                    self.evaluations[eval_id]["status"] = "running"

                    result = await test_runner.run_tests(eval_id)

                    if result:
                        #update stats
                        self.projects_processed += 1
                        self.tests_passed += result.passed
                        self.tests_failed += result.failed

                        # update eval status
                        self.evaluations[eval_id]["status"] = "completed"
                        self.evaluations[eval_id]["result"] = result.to_dict()

                    else:
                        # update eval status
                        self.evaluations[eval_id]["status"] = "failed"
                        self.evaluations[eval_id]["error"] = "Failed to run tests"

                    # clean up project
                    await self.cleanup_project(eval_id)

                except Exception as e:
                    logging.error(f"Error processing project {eval_id}: {e}")
                    self.evaluations[eval_id]["status"] = "failed"
                    self.evaluations[eval_id]["error"] = str(e)

            except asyncio.CancelledError:
                break

            except Exception as e:
                logging.error(f"Error in project processing loop: {e}")

            await asyncio.sleep(0.1)

    async def download_project(self, url:str, token:str = None, eval_id:str = "downloaded") -> bool:
        "downloads the project from the given url"
        try:
            if url.startswith("https://github.com") :
                from utils.functions import download_github_repo
                return await download_github_repo(url, token, eval_id)

            else:
                logging.error(f"Unsupported url: {url}")
                return False

        except Exception as e:
            logging.error(f"Error downloading project: {e}")
            return False

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

        if not self.protocol:
            raise RuntimeError("Protocol not initialized. Ensure the protocol is started.")

        while self.is_running:
            try:
                message, addr = await self.protocol.recv()

                # TODO: process message
                logging.info(f"Received message from {addr}: {message}")

            except asyncio.CancelledError:
                break

            except Exception as e:
                logging.error(f"Error in message listening loop: {e}")

            await asyncio.sleep(0.1)
