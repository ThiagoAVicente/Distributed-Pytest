"""
computação distribuída - UA
Thiago Vicente e Diogo Duarte
"""

import xml.etree.ElementTree as ET
import os
import asyncio

async def passedFromFile(filePath:str = "out.xml") -> tuple[int,int] | None:
    "Expects a .xml file and returns the amount of passed tests"

    """returns a tuple where the first element is the amount of passed tests
    and the second is the total amount of tests"""

    filePath = filePath.strip()

    # ensure that an .xml is passed
    if not filePath.endswith(".xml"): return None

    def parse():
        try:
            tree = ET.parse(filePath)
            root = tree.getroot()

            target = root.find("testsuite") # find the result tag
            if target is None: return -1,-1 # not a valid xml for this


            # get values from target
            total_tests:int = int( target.attrib["tests"] )
            failures:int = int( target.attrib["failures"] )
            errors:int = int( target.attrib["errors"] )
            skipped:int = int( target.attrib["skipped"] )

            passed = total_tests - failures - errors - skipped
            failed = failures  #TODO veridy if erros and skipped are included in failures

            return passed,failed

        except Exception as e:
            print(f"Error parsing XML file: {e}")
            return None

    # return the amount of passed tests
    return await asyncio.to_thread(parse)

def countModulesFromFile(xml_path: str = "out.xml") -> int:
    # print(123)
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()
        classnames = {
            case.attrib.get("classname")
            for case in root.iter("testcase")
            if "classname" in case.attrib
        }
        return len(classnames)
    except Exception as e:
        print(f"Error parsing XML: {e}")
        return 0

async def pytestCall(folder:str) -> tuple[int,int] | None:
    "run pytest"
    # print(f"Running pytestall on {folder}")

    # save working directory
    original_cwd = os.getcwd()
    output_filePath = os.path.join( original_cwd,"out.xml")

    try:

        await asyncio.create_subprocess_exec(
            "pytest",
            f"--junit-xml={output_filePath}",
            "-p",
            "no:terminal",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=folder                          # change working directory
        )

        return await passedFromFile(output_filePath)

    except Exception as e:
            print(f"Error running unit tests: {e}")
            return None

    # return the amount of passed tests
    return None

async def downloadFromGithub(token:str,url:str, dest:str = ".") -> str:
    """
    Asynchronously download a repository from github using credentians and unzip itn

    token: user authentication token
    url: url to the repository
    dest: path where to save the repository

    returns the path to the repository
    """

    # imports
    import urllib.request

    # create dest if it does not exist
    if not os.path.exists(dest):
        os.makedirs(dest)

    if not url.startswith("https://github.com/"):
        raise ValueError("Invalid github URL.")

    if "#" in url:
        url = url.split("#")[0]

    # get the user and repo name
    parts = url.replace("https://github.com/", "").strip("/").split("/")
    if len(parts) < 2:
        raise ValueError("Invalid GitHub repository URL format")
    user, repo = parts[0], parts[1]

    # prepare url for downloading
    zip_url:str = f"https://api.github.com/repos/{user}/{repo}/zipball"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    def download():

        # nonblocking request
        req = urllib.request.Request(zip_url, headers=headers)

        with urllib.request.urlopen(req) as response:

            # check response status
            if response.status != 200:
                raise RuntimeError(f"Failed to download zip: {response.status}")

            # save atemp zip file
            zip_path = os.path.join(dest, "repo.zip")
            with open(zip_path, "wb") as zip_file:
                zip_file.write(response.read())
            return zip_path


    # save zip file
    zip_path = await asyncio.to_thread(download)

    extracted_path = await unzipFolder(zip_path, dest)

    # remove temp zip
    os.remove(zip_path)

    return extracted_path

async def removeDir(path:str) -> None:
    "remove a directory and all its contents"
    import shutil
    if os.path.exists(path):
        await asyncio.to_thread(shutil.rmtree, path)

async def unzipFolder(zipPath:str, dest:str = ".") -> str:
    "unzip a folder"

    import zipfile

    if not os.path.exists(dest):
        os.makedirs(dest)

    def extract() -> str:
        with zipfile.ZipFile(zipPath, 'r') as zip_ref:
            zip_ref.extractall(dest)
            top_folder = zip_ref.namelist()[0].split("/")[0]
            extracted_path = os.path.join(dest, top_folder)

            return extracted_path

    extracted_path:str = await asyncio.to_thread(extract)
    return extracted_path

async def verifyFolder(path:str) -> bool:
    "verify if dir has tests folder"

    import glob

    # check if the path exists
    if not os.path.exists(path):
        return False

    # check if there is a tests folder
    if not os.path.exists(os.path.join(path, "tests")):
        return False

    # check if there are any test files
    if not glob.glob(os.path.join(path, "tests", "test_*.py")):
        return False

    return True

async def reduceString(s:str,sz:int) -> str:
    if sz <= 3:
        raise ValueError("Size must be greater than 3")

    truncated= (s[:sz-3] + '...') if len(s) > sz else s

    return truncated
