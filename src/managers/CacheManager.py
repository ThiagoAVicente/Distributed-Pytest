import time
import logging
from typing import Dict, Any, List
from managers.BaseManager import BaseManager

EPS = 1e-6  

class CacheManager(BaseManager):
    def __init__(self, node_context):
        super().__init__(node_context)
        
        # Network cache structure
        self.network_cache: Dict[str, Dict[str, Any]] = {
            "evaluations": {},    # contains the evaluations and their projects names
            "projects": {},       # contains the projects and their status
            "status": {},         # contains the status of the nodes
        }
            
    async def start(self):
        """
        Initialize the cache manager
        This method does nothing hahahaha
        """
        logging.info("CacheManager started")
        
    async def stop(self):
        """
        Stop the cache manager
        :^)
        """
        self.clear_cache()
        logging.info("CacheManager stopped")
        
    def get_cache(self) -> Dict[str, Dict[str, Any]]:
        """Get the entire network cache"""
        return self.network_cache.copy()
        
    def get_evaluations_cache(self) -> Dict[str, Any]:
        """Get evaluations cache"""
        return self.network_cache["evaluations"].copy()
        
    def get_projects_cache(self) -> Dict[str, Any]:
        """Get projects cache"""
        return self.network_cache["projects"].copy()
        
    def get_status_cache(self) -> Dict[str, Any]:
        """Get status cache"""
        return self.network_cache["status"].copy()
    
    def del_node_status(self,node_id):
        """Delete a node status from cache"""
        if node_id in self.network_cache["status"]:
            del self.network_cache["status"][node_id]
            logging.debug(f"Deleted status for node {node_id} from cache")
        else:
            logging.warning(f"Node {node_id} not found in status cache")
    
    def create_evaluation(self, eval_id: str) -> None:
        """Create a new evaluation entry in cache"""
        if eval_id not in self.network_cache["evaluations"]:
            self.network_cache["evaluations"][eval_id] = {
                "projects": [],
                "start_time": time.time(), # start time counter
                "end_time": None
            }
            logging.debug(f"Created evaluation {eval_id} in cache")
            
    def create_project(self, project_id: str, node_addr: str, project_name: str) -> None:
        """Create a new project entry in cache"""
        if project_id not in self.network_cache["projects"]:
            self.network_cache["projects"][project_id] = {
                "project_name": project_name,
                "node": node_addr,
                "modules": {}
            }
            logging.debug(f"Created project {project_id} in cache")
            
    def create_module(self, project_id: str, module_name: str) -> None:
        """Create a new module entry in project cache"""
        if project_id in self.network_cache["projects"]:
            if module_name not in self.network_cache["projects"][project_id]["modules"]:
                self.network_cache["projects"][project_id]["modules"][module_name] = {
                    "passed": 0,
                    "failed": 0,
                    "time": 0,
                    "status": "pending"
                }
                logging.debug(f"Created module {module_name} for project {project_id}")
                
    def add_project_to_evaluation(self, eval_id: str, project_id: str) -> None:
        """Asoociates a project with an evaluation"""
        if eval_id in self.network_cache["evaluations"]:
            if project_id not in self.network_cache["evaluations"][eval_id]["projects"]:
                self.network_cache["evaluations"][eval_id]["projects"].append(project_id)
                logging.debug(f"Added project {project_id} to evaluation {eval_id}")
                
    def update_module_status(self, project_id: str, module_name: str, status: str) -> None:
        """Update module status"""
        if project_id in self.network_cache["projects"]:
            if module_name in self.network_cache["projects"][project_id]["modules"]:
                self.network_cache["projects"][project_id]["modules"][module_name]["status"] = status
                logging.debug(f"Updated module {module_name} status to {status}")
                
    def update_module_results(self, project_id: str, module_name: str, passed: int, failed: int, time_taken: float) -> None:
        """Update module test results"""
        if project_id in self.network_cache["projects"]:
            if module_name in self.network_cache["projects"][project_id]["modules"]:
                module_data = self.network_cache["projects"][project_id]["modules"][module_name]
                module_data["passed"] = passed
                module_data["failed"] = failed
                module_data["time"] = time_taken
                module_data["status"] = "finished"
                
                # Check if all modules in all projects of evaluations are finished
                self._check_evaluation_completion(project_id)
                logging.debug(f"Updated module {module_name} results: {passed} passed, {failed} failed")
                
    def _check_evaluation_completion(self, project_id: str) -> None:
        """
        Check if evaluations containing this project are complete
        Update the end time if all projects are done 
        """
        for eval_id, eval_data in self.network_cache["evaluations"].items():
            if project_id in eval_data["projects"]:
                all_finished = all(
                    self.network_cache["projects"][p]["modules"][m]["status"] == "finished"
                    for p in eval_data["projects"]
                    if p in self.network_cache["projects"]
                    for m in self.network_cache["projects"][p]["modules"]
                )
                if all_finished and not eval_data["end_time"]:
                    eval_data["end_time"] = time.time()
                    logging.info(f"Evaluation {eval_id} completed")
                    
                break # a project can only belong to 1 eval
                    
    def get_evaluation_status(self, eval_id: str) -> Dict[str, Any] | None:
        """Get evaluation status with detailed information"""
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
        
        # Calculate time elapsed
        if eval_data["end_time"]:
            result["time_elapsed"] = eval_data["end_time"] - eval_data["start_time"]
        elif eval_data["start_time"]:
            result["time_elapsed"] = time.time() - eval_data["start_time"]

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
            if project_name not in result["projects"]:
                result["projects"][project_name] = project_result
            else:
                result["projects"][f"{project_name}_{len(result["projects"])}"] = project_result

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
    
        return result
        
    def get_all_evaluations(self) -> List[str]:
        """Get all evaluation IDs"""
        return list(self.network_cache["evaluations"].keys())
        
    def get_network_schema(self, node_peers) -> Dict[str, List[str]]:
        "returns the network schema ( mesh :) )"
        d = {node: data["net"] for node, data in self.network_cache["status"].copy().items()}
        d[f"{self.node_context.outside_ip}:{self.node_context.outside_port}"] = node_peers
        return d
        
    def update_node_status(self, node_addr: str, peers_ip: List[str], stats: Dict[str, Any]) -> None:
        """Update node status in cache ( net and process stats )"""
        self.network_cache["status"][node_addr] = {
            "net": peers_ip,
            "stats": stats
        }
        logging.debug(f"Updated status for node {node_addr}")
        
    def merge_cache_update(self, node_addr: str, cache_data: Dict[str, Any]) -> None:
        """Merge cache update from another node"""
        peers_ip = cache_data.get("peers_ip", [])
        evaluations = cache_data.get("evaluations", {})
        projects = cache_data.get("projects", {})
        stats = cache_data.get("stats", {})
        
        # Update node status
        self.update_node_status(node_addr, peers_ip, stats)
        
        # Merge evaluations
        for e_id, e_data in evaluations.items():
            if e_id not in self.network_cache["evaluations"]:
                self.network_cache["evaluations"][e_id] = {
                    "projects": e_data["projects"].copy(),
                    "start_time": e_data["start_time"],
                    "end_time": e_data["end_time"]
                }
            else:
                # Merge data
                current = self.network_cache["evaluations"][e_id]
                current["projects"] = list(set(current["projects"]) | set(e_data["projects"]))
                if current["end_time"] is None :
                    current["end_time"] = e_data["end_time"]
                    
        # Merge projects
        for p_id, p_data in projects.items():
            if p_id not in self.network_cache["projects"]:
                self.network_cache["projects"][p_id] = {
                    "node": p_data["node"],
                    "modules": p_data["modules"].copy(),
                    "project_name": p_data["project_name"],
                }
            else:
                # Merge projects
                current_modules = self.network_cache["projects"][p_id]["modules"]
                for module_name, module_data in p_data["modules"].items():
                    if module_name not in current_modules or module_data["status"] == "finished":
                        current_modules[module_name] = module_data.copy()
                    elif module_data["status"] == "running" and current_modules[module_name]["status"] == "pending":
                        current_modules[module_name]["status"] = "running"
                        
        logging.debug(f"Merged cache update from {node_addr}")
        
    def prepare_cache_for_propagation(self, node_ip: str, node_port: str, peers_ip: List[str], node_stats: Dict[str, Any]) -> Dict[str, Any]:
        """Prepare cache data for network propagation"""
        return {
            "addr": f"{node_ip}:{node_port}",
            "peers_ip": peers_ip,
            "evaluations": self.network_cache["evaluations"],
            "projects": self.network_cache["projects"],
            "stats": node_stats,
        }
    
    def clear_cache(self) -> None:
        """Clear the entire cache"""
        self.network_cache = {
            "evaluations": {},
            "projects": {},
            "status": {},
        }
        logging.info("Cache cleared")