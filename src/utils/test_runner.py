"""
implements methods to run pytest
"""

import asyncio
import os
import logging
import pytest
from typing import Dict, Optional, Any
import xml.etree.ElementTree as ET

class TestResult:
    "represents the result of a test"

    def __init__(self, passed: int, failed: int, modules: int):
            self.passed = passed
            self.failed = failed
            self.total = passed + failed
            self.modules = modules

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

    async def run_tests(self,eval_id:str,project_name:str, module:str) -> Optional[TestResult]:
        "runs tests and returns results"

        try:

            # create paths
            project_path = os.path.join(os.getcwd(), eval_id,project_name, "tests")
            xml_output = os.path.join(os.getcwd(), f"{eval_id}.xml")

            # Verify project path exists
            if not os.path.exists(project_path):
                logging.error(f"Project path does not exist: {project_path}")
                return None

            # run pytest
            proc = await asyncio.create_subprocess_exec(
                "pytest",
                module,
                f"--junitxml={xml_output}",
                "-p", "no:terminal",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_path,
                env = self.env
            )

            stdout, stderr = await proc.communicate()

            if proc.returncode >= 2: # pytest error
                logging.error(f"Error running tests: {stderr.decode()}")
                return None

            res = await self.parse_results(xml_output)

            # remove xml file
            if os.path.exists(xml_output):
                os.remove(xml_output)

            return res

        except Exception as e:
            logging.error(f"Error running tests: {e}")
            return None

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

            # get number of modules - corrected to find testcase elements inside testsuite
            modules = len(testsuite.findall("testcase"))

            # calculate passed tests
            passed = tests - (failures + errors + skipped)

            return TestResult(passed, failures + errors, modules)
        except Exception as e:
            logging.error(f"Error parsing xml file: {e}")
            return TestResult(0, 0, 0)

    async def get_modules(self,eval_id:int, project_name: str) -> list[str]:
        "get alll pytest modules in the given path"
        
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(None, self._get_modules, eval_id,project_name)
        except Exception as e:
            logging.error(f"Error getting modules: {e}")
            return None
    
    def _get_modules(self,eval_id:int, project_name: str) -> list[str]:
        
        # check if path exists
        path = os.path.join(os.getcwd(), str(eval_id), project_name, "tests")
        
        if not os.path.exists(path):
            logging.error(f"Path does not exist: {path}")
            return None
            
        modules = set() 
        
        class Collector:
            def pytest_collectreport(self, report):
                if report.passed:
                    nodeid = report.nodeid
                    
                    if nodeid.endswith(".py"):
                        module = nodeid.split("::")[0].split("/")[-1]
                        modules.add(module)
                    
        
        pytest.main([
            '--collect-only',
            "-p", "no:terminal",
            path,
        ], plugins=[Collector()])
        
        return list(modules)