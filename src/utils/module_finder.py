import os
import sys
import pytest
import subprocess
import tempfile

def install_requirements(project_path):
    requirements_path = os.path.join(project_path, "requirements.txt")
    if os.path.exists(requirements_path):
        #print(f"[INFO] Installing requirements from {requirements_path}", file=sys.stderr)
        try:
            # redirect stdoutto a temporary file to avoid cluttering the output
            with tempfile.TemporaryFile() as temp_f:
                subprocess.check_call(
                    ["pip", "install", "-r", requirements_path],
                    stdout=temp_f,
                    stderr=subprocess.STDOUT
                )
            return True
        except subprocess.CalledProcessError as e:
            print(f"[ERROR] Failed to install requirements: {e}", file=sys.stderr)
            return False
    return True
    
def find_modules(project_path):
    "find the modules in the project"
    
    if not os.path.exists(project_path):
        print("[ERROR] Project path does not exist", file=sys.stderr)
        return  []
    
    project_root = os.path.dirname(project_path)    
    
    if not install_requirements(project_root):
        return []
        
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
        project_path,
    ], plugins=[Collector()])
    
    return sorted(modules)
    
if __name__ == "__main__":
    project_name = sys.argv[1]

    project_tests_path = os.path.join(os.getcwd(), project_name, "tests")
    for m in find_modules(project_tests_path):
        print(m)