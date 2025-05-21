"""
implements methods to run pytest
"""

import asyncio
import os
import logging
import sys
import shutil
from typing import Dict, Optional, Any
import xml.etree.ElementTree as ET

PYTESTMAXTIME:int = 25

class TestResult:
    "represents the result of a test"

    def __init__(self, passed: int, failed: int, modules: int, time: float = 0):
            self.passed = passed
            self.failed = failed
            self.total = passed + failed
            self.modules = modules
            self.time = time # in seconds

    @property
    def success_rate(self) -> float:
        "success rate of the test"
        if self.total == 0:
            return 0
        return (self.passed / self.total) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total,
            "success_rate": self.success_rate,
            "modules": self.modules
            }


class PytestRunner:
    " handles test execution"

    def __init__(self, work_dir: str = None):
        self.work_dir = work_dir or os.getcwd()
        env = os.environ.copy()
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        self.env = env
        self._original_modules = set()
        self._snapshot_modules()
        
    def _snapshot_modules(self):
        self._original_modules = set(sys.modules.keys())    
    
    def _restore_modules(self):
        current_modules = set(sys.modules.keys())
        new_modules = current_modules - self._original_modules
        for mod in new_modules:
            sys.modules.pop(mod, None)
    
    async def run_tests(self,  project_name: str, module: str) -> Optional["TestResult"]:
        project_root = os.path.join(self.work_dir,  project_name)
        test_path = os.path.join(project_root, "tests")
        module_path = os.path.join(test_path, module)
        xml_output = os.path.join(project_root, f"results_{project_name}.xml")

        try:
            if not os.path.isdir(test_path):
                logging.error(f"Project test path does not exist: {test_path}")
                return None

            if not os.path.exists(module_path):
                logging.error(f"Test module path does not exist: {module_path}")
                return None

            # install requirements
            requirements_path = os.path.join(project_root, "requirements.txt")
            if os.path.exists(requirements_path):
                logging.debug(f"Installing requirements from {requirements_path}")
                proc = await asyncio.create_subprocess_exec(
                    "pip", "install", "-r", requirements_path,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=project_root,
                    env=self.env,
                )
                stdout, stderr = await proc.communicate()
                if proc.returncode != 0:
                    logging.error(f"Failed to install requirements:\n{stderr.decode()}")
                    return None

            # prepare command
            pytest_cmd = [
                "pytest",
                module_path,
                f"--junitxml={xml_output}",
                "-p", "no:terminal",
            ]
            # run pytest
            proc = await asyncio.create_subprocess_exec(
                *pytest_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_root,
                env=self.env,
            )
            # run pytest
            try:
                process_task = asyncio.create_task(proc.communicate())
                stdout, stderr = await asyncio.wait_for(process_task, timeout=PYTESTMAXTIME)
            except asyncio.TimeoutError:
                logging.warning(f"Test execution timed out after {PYTESTMAXTIME} seconds, terminating process")
                # force process to stop
                proc.kill()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    logging.error("Process could not be terminated properly")
                
                # Return a result that indicates timeout
                return TestResult(0, 1, 1, PYTESTMAXTIME) 

            if proc.returncode >= 2:
                logging.error(f"Pytest internal errors:\n{stderr.decode()}")
                return None
            elif proc.returncode == 1:
                logging.warning(f"Some tests failed:\n{stderr.decode()}")

            if not os.path.exists(xml_output):
                logging.error("JUnit XML file was not created")
                return None

            result = await self.parse_results(xml_output)
            return result

        except Exception as e:
            logging.error(f"Error running tests: {e}")
            return None

        finally:
            try:
                self._restore_modules()

                # clean 
                if os.path.exists(xml_output):
                    os.remove(xml_output)

                pytest_cache = os.path.join(os.getcwd(), ".pytest_cache")
                if os.path.exists(pytest_cache):
                    shutil.rmtree(pytest_cache, ignore_errors=True)

                for root, dirs, _ in os.walk(test_path):
                    for d in dirs:
                        if d in ("__pycache__", ".pytest_cache"):
                            shutil.rmtree(os.path.join(root, d), ignore_errors=True)

            except Exception as e:
                logging.warning(f"Error during cleanup: {e}")
                    
    async def parse_results(self, xml_path: str) -> TestResult:
        "read results from xml"
        try:

            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._parse_xml, xml_path)
        except Exception as e:
            logging.error(f"Error parsing test results: {e}")
            return TestResult(0, 0, 0)

    def _parse_xml(self, xml_path: str) -> TestResult:
        "parse xml file"
        # logging.info("parse xml " +xml_path)
        try:
            tree = ET.parse(xml_path)
            root = tree.getroot()

            # get testsuite
            testsuite = root.find("testsuite")

            # Check if testsuite is not None
            if testsuite is None:
                logging.warning("No testsuite element found in XML")
                return TestResult(0, 0, 0)

            # get number of tests
            tests = int(testsuite.attrib["tests"])
            failures = int(testsuite.attrib["failures"])
            errors = int(testsuite.attrib["errors"])
            skipped = int(testsuite.attrib["skipped"])
            time = float(testsuite.attrib["time"])

            # get number of modules - corrected to find testcase elements inside testsuite
            modules = len(testsuite.findall("testcase"))

            # calculate passed tests
            passed = tests - (failures + errors + skipped)

            return TestResult(passed, failures + errors, modules, time)
        except Exception as e:
            logging.error(f"Error parsing xml file: {e}")
            return TestResult(0, 0, 0)

    async def get_modules(self, project_name: str) -> list[str]:
        """get all pytest modules in the given path using a separate process"""
        try:
            finder_path = os.path.join(os.path.dirname(__file__), "module_finder.py")
            
            
            # run script
            prco = await asyncio.create_subprocess_exec(
                "python", finder_path, project_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.work_dir,
                env=self.env
            )
            
            stdout, stderr = await prco.communicate()
            #logging.debug(stdout.decode())
            #logging.debug(stderr.decode())
            if prco.returncode != 0:
                logging.error(f"Error finding modules: {stderr.decode()}")
                return []
                
            # parse output
            modules_o = stdout.decode().strip()
            if not modules_o:
                logging.warning("No modules found")
                return []
                
            modules = [ line for line in modules_o.split("\n") if line.strip() ]
            return modules
        except Exception as e:
            logging.error(f"Error finding modules: {e}")
            return []