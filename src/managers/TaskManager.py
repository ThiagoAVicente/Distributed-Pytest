import time
import logging
import asyncio
import os
from functools import partial
from typing import Dict, Any, Optional, Tuple, Set
from managers.BaseManager import BaseManager
from utils.test_runner import PytestRunner

# Constants
GIVEN_TASK: int = 1
DIRECTLY_PROJECT: int = 0
TASK_TIMEOUT:float = 40.0

class TaskManager(BaseManager):
    def __init__(self, node_context):
        super().__init__(node_context)
        self.main_task = None

        # task variables
        self.task_queue: asyncio.Queue = asyncio.Queue()

        # Priority queue for tasks that are late
        self.task_priority_queue: asyncio.Queue = asyncio.Queue()

        #Tasks sent to other nodes, task_id : (node_address, time_sent)
        self.task_responsibilities: Dict[str, Tuple[Tuple[str, int], float]] = {}
        self.task_results: Dict[str, Dict[str, Any]] = {}
        self.external_task: Optional[Tuple[str, str]] = None

        # task_id : time--> stores the tasks waiting for confirmation
        self.expecting_confirm: Dict[str, float] = {}

        # evaluations that were processed in this node
        self.processed_evaluations: Set[str] = set()

        # projects that were processed in this node
        self.processed_projects: Set[str] = set()

        self.test_runner = PytestRunner(os.getcwd())

    async def start(self):
        self.main_task = asyncio.create_task(self._process_queue())
        logging.debug("TaskManager started")

    async def stop(self):
        if self.main_task:
            self.main_task.cancel()
            try:
                await self.main_task
            except asyncio.CancelledError:
                pass
            self.main_task = None

        logging.debug("TaskManager stopped")

    async def process_task(self, project_id: str, module: str,source:int):
        result = await self.test_runner.run_tests(project_id, module)
        if result:

            self.processed_projects.add(project_id)
            evaluations_cache = self.node_context.cache_manager.get_evaluations_cache()
            for e_id, e_data in evaluations_cache.items():
                if project_id in e_data["projects"]:
                    self.processed_evaluations.add(e_id)
                    break

            # update node stats
            self.node_context.tests_passed += result.passed
            self.node_context.tests_failed += result.failed
            self.node_context.modules += 1

            if source == DIRECTLY_PROJECT:
                logging.debug(f"Processed {project_id}::{module}")
                # update project status
                self.node_context.cache_manager.update_module_results(project_id, module, result.passed, result.failed, result.time)

            elif source == GIVEN_TASK:
                logging.debug(f"Processed {project_id}::{module}")
                task_id = f"{project_id}::{module}"

                # update task status
                addr = self.task_results[task_id]["node"]

                # send task results via http
                url = f"http://{addr[0]}:{addr[1]}/task"
                info = {
                    "task_id": task_id,
                    "passed": result.passed,
                    "failed": result.failed,
                    "time": result.time,
                    "project_id": project_id,
                    "module": module,
                    "ip": self.node_context.outside_ip,
                    "port": self.node_context.outside_port,
                }

                await asyncio.get_event_loop().run_in_executor(
                    None,
                    partial(self.node_context.send_http_post, url, info)
                )

                del self.task_results[task_id]
                logging.debug(f"Sent task result to {url}")

            await self.node_context._propagate_cache()

        else:
            logging.error(f"Error processing {project_id}::{module}")

    async def _process_queue(self):
        """Process task queue"""
        logging.debug("TaskManager started processing queue")

        while self.node_context.is_running:
            try:
                source = DIRECTLY_PROJECT

                # external tasks are priority
                if self.external_task:
                    project_id, module = self.external_task
                    self.external_task = None
                    source = GIVEN_TASK

                # If priority queue not empty, it should be handled first
                elif not self.task_priority_queue.empty():
                    # Get one task from the priority queue
                    project_id, module = await asyncio.wait_for(self.task_priority_queue.get(), timeout=1)
                    logging.info(f"Processing high priority task {project_id}::{module}")

                elif not self.task_queue.empty():
                    project_id, module = await asyncio.wait_for(self.task_queue.get(), timeout=1)
                    self.node_context.cache_manager.update_module_status(project_id, module, "running")

                else:
                    await asyncio.sleep(0.1)
                    continue

                self.node_context.is_working = True
                await self.node_context._propagate_cache()

                logging.debug(f"Processing {project_id}::{module}")

                await self.process_task(project_id,module,source)

                # update project status
                self.node_context.is_working = False

            except asyncio.TimeoutError:
                continue

            except asyncio.CancelledError:
                break

            except Exception as e:
                logging.error(f"Error in project processing loop: {e}")

            await self.cleanup_expired_responsibilities()
            await asyncio.sleep(0.01)

        logging.debug("TaskManager stopped processing queue")
        return

    async def handle_task_request(self, message: dict, addr: Tuple[str, int]):
        """Handle task request from another node"""
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
            evaluations_cache = self.node_context.cache_manager.get_evaluations_cache()
            for e_id, e_data in evaluations_cache.items():
                if project_id in e_data["projects"]:
                    eval_id = e_id
                    break

            projects_cache = self.node_context.cache_manager.get_projects_cache()
            project_name = projects_cache.get(project_id, {}).get("project_name", project_id)

            temp = self.node_context.urls.get(project_id, None)

            data = {
                "project_id": project_id,
                "module": module,
                "project_name": project_name,
                "api_port": os.environ.get("API_PORT", "5000"),  # send api port to receive results
                "eval_id": eval_id,
                "url": temp[0] if temp else None,
                "token": temp[1] if temp else None,
                "type": "url" if temp else "zip",
            }

            self.expecting_confirm[f"{project_id}::{module}"] = time.time()
            self.node_context.network.task_send(addr, data)  # type: ignore
            logging.debug(f"Sending task {project_id}::{module} to {addr}")

    async def handle_task_confirm(self, message: dict, addr: Tuple[str, int]):
        """Handle task confirmation from worker node"""
        task_id = message["data"]["task_id"]

        if task_id in self.expecting_confirm:
            del self.expecting_confirm[task_id]
            # get project_id and module from task_id
            project_id, module = task_id.split("::")
            # set task as running
            self.node_context.cache_manager.update_module_status(project_id, module, "running")

            # add responsibility for the task
            self.task_responsibilities[f"{project_id}::{module}"] = (addr, time.time())
            logging.debug(f"Task {task_id} confirmed by {addr}")
        else:
            logging.error(f"Task {task_id} not found in expecting confirm")

    async def handle_task_send(self, message: dict, addr: Tuple[str, int]):
        """Handle incoming task assignment"""
        if self.external_task:
            logging.debug(f"Task {self.external_task} already in progress")
            return

        project_id = message["data"]["info"]["project_id"]
        module = message["data"]["info"]["module"]
        api_port = message["data"]["info"]["api_port"]
        eval_id = message["data"]["info"]["eval_id"]

        # check if folder was already downloaded
        if project_id in os.listdir(os.getcwd()):
            self.external_task = (project_id, module)
            self.create_task((addr[0], api_port), project_id, module, eval_id)
            self.node_context.network.task_confirm(addr, {"task_id": f"{project_id}::{module}"})  # type: ignore
            return

        # download project from github
        project_info = await self.node_context.request_project(message)
        if project_info:
            project_id, project_name = project_info
            self.create_task((addr[0], api_port), project_id, module, eval_id)
            self.external_task = (project_id, module)

            # notify node
            self.node_context.network.task_confirm(addr, {"task_id": f"{project_id}::{module}"})  # type: ignore

    async def handle_task_result(self, task_id: str, info: Dict) -> bool:
        """Process task result message from a worker node"""
        project_id = info["project_id"]
        module = info["module"]
        ip = info["ip"]
        port = info["port"]
        addr = (ip, port)

        # Get the current node's address
        my_addr = f"{self.node_context.outside_ip}:{self.node_context.outside_port}"
        # Get the responsible node from cache
        responsible_node = None
        responsible_node_str = None

        projects_cache = self.node_context.cache_manager.get_projects_cache()
        if project_id in projects_cache:
            responsible_node_str = projects_cache[project_id].get("node")
            if responsible_node_str:
                try:
                    ip, port_str = responsible_node_str.split(":")
                    responsible_node = (ip, int(port_str))
                except Exception as e:
                    logging.warning(f"Error parsing responsible node address {responsible_node_str}: {e}")

        def update_cache(project_id: str, module: str, message: dict):
            # update project status using cache manager
            self.node_context.cache_manager.update_module_results(project_id, module, message["passed"], message["failed"], message["time"])

            # mark evaluation as processed
            evaluations_cache = self.node_context.cache_manager.get_evaluations_cache()
            for eval_id, eval_data in evaluations_cache.items():
                if project_id in eval_data["projects"]:
                    self.processed_evaluations.add(eval_id)

        # Check if this node is the responsible node
        is_responsible = responsible_node_str == my_addr

        # Process the result if this node is still responsible or is the new responsible node
        if is_responsible:
            # remove responsibility entry
            del self.task_responsibilities[task_id]

            update_cache(project_id, module, info)

            # inform node that successfully finished
            logging.debug(f"Received task result from {addr}")
            await self.node_context._propagate_cache()
            return True

        # If the responsible node changed and it's not this node, forward the result
        elif responsible_node:
            if responsible_node:
                logging.info(f"Forwarding task result {task_id} to the new responsible node {responsible_node}")

                url = f"http://{responsible_node[0]}:{responsible_node[1]}/task"

                try:
                    await asyncio.get_event_loop().run_in_executor(
                        None,
                        partial(self.node_context.send_http_post, url, info)
                    )
                    return True
                except Exception as e:
                    logging.error(f"Error processing task result: {e}")
                    return False

        logging.warning("could not do anything with task result. Hoping the tracker finds the problem :)")
        return False

    def create_task(self, addr: Tuple[str, int], project_id: str, module_name: str, eval_id: Optional[str] = None):
        """Creates a new task entry"""
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

    async def reassign_tasks(self, node_saddr: str):
        """Reassign tasks from a failed node"""
        # Redistribute tasks
        tasks_to_reassign = [task_id for task_id, info in self.task_responsibilities.items()
                            if f"{info[0][0]}:{info[0][1]}" == node_saddr]
        for task_id in tasks_to_reassign:
            del self.task_responsibilities[task_id]
            await self.add_task_to_priority_queue(task_id)
            logging.info(f"Reassigned task {task_id} from failed node {node_saddr}")

    async def add_task_to_priority_queue(self, task_id: str):
        """Add a task to the priority queue, extracting project_id and module from task_id"""
        try:
            project_id, module = task_id.split("::")
            await self.task_priority_queue.put((project_id, module))
            logging.info(f"Task {task_id} added to priority queue")
            return True
        except Exception as e:
            logging.error(f"Error adding task to priority queue: {e}")
            return False

    async def add_task_to_queue(self, project_id: str, module: str):
        """Add a task to the regular task queue"""
        await self.task_queue.put((project_id, module))
        logging.debug(f"Added task {project_id}::{module} to queue")

    def get_queue_size(self) -> int:
        """Get the size of the task queue"""
        return self.task_queue.qsize()

    def get_priority_queue_size(self) -> int:
        """Get the size of the priority queue"""
        return self.task_priority_queue.qsize()

    async def cleanup_expired_confirmations(self, timeout: float = 10.0):
        """Clean up expired task confirmations and requeue them"""
        current_time = time.time()
        expired_tasks = [task_id for task_id, timestamp in self.expecting_confirm.items()
                        if current_time - timestamp > timeout]

        for task_id in expired_tasks:
            del self.expecting_confirm[task_id]
            logging.warning(f"Task confirmation expired for {task_id}")
            # Put in priority queue for faster termination
            await self.add_task_to_priority_queue(task_id)

    async def cleanup_expired_responsibilities(self):
        current_time = time.time()
        expired_tasks = [task_id for task_id, (addr, timestamp) in self.task_responsibilities.items()
                        if current_time - timestamp > TASK_TIMEOUT]

        # reassign tasks
        for task_id in expired_tasks:
            addr, _ = self.task_responsibilities[task_id]
            del self.task_responsibilities[task_id]
            await self.add_task_to_priority_queue(task_id)
            logging.warning(f"Task {task_id} expired and reassigned from {addr}")

    def get_processed_projects(self) -> Set[str]:
        """Get set of processed project IDs"""
        return self.processed_projects.copy()

    def get_processed_evaluations(self) -> Set[str]:
        """Get set of processed evaluation IDs"""
        return self.processed_evaluations.copy()
