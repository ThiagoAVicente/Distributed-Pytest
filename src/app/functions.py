"""
computação distribuída - UA
Thiago Vicente e Diogo Duarte
"""

import pytest
import xml.etree.ElementTree as ET
import os

def passedFromFile(filePath:str) -> int:
    "Expects a .xml file and returns the amount of passed tests"

    filePath = filePath.strip()

    # ensure that an .xml is passed
    if not filePath.endswith(".xml"): return -1

    tree = ET.parse(filePath)
    root = tree.getroot()

    target = root.find("testsuite") # find the result tag
    if target is None: return -1 # not a valid xml for this
    
    passed:int = 0
    try:
        # get values from target
        total_tests:int = int( target.attrib["tests"] )
        failures:int = int( target.attrib["failures"] )
        errors:int = int( target.attrib["errors"] )
        skipped:int = int( target.attrib["skipped"] )
        
        passed = total_tests - failures - errors - skipped
    except :
        passed = -1 # fail
    
    # remove out.xml
    if os.path.exists(filePath):
        os.remove(filePath)
    
    # return the amount of passed tests
    return passed

def unitTest(testPath:str) -> int:
    "run pytest on a single test file"

    # write the test results to out.xml
    pytest.main([testPath,"--junit-xml=out.xml","-p no:terminal"])

    # return the amount of passed tests
    return passedFromFile("out.xml")

def getAllTests(testPath:str = "g4/tests") -> list:
    "get all tests from a directory"

    collected:list = []

    # create a custom collector to save the tests
    class Colector:
        def pytest_collection_modifyitems(self,session,config,items):
            for item in items:
                collected.append(item.nodeid)

    pytest.main([testPath,"--collect-only","-p no:terminal"], plugins=[Colector()])
    return collected

def downloadFromGithub(token:str,url:str, dest:str = ".") -> str:
    """
    Download a repository from github using credentians and unzip itn

    token: user authentication token
    url: url to the repository
    dest: path where to save the repository

    returns the path to the repository
    """

    # imports
    import zipfile
    import requests
    import io

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
            "Authorization":f"{token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }

    #print(f"Downloading from {zip_url}")
    response = requests.get(zip_url, headers=headers)

    if response.status_code != 200:
        raise RuntimeError(f"Failed to download zip: {response.status_code} - {response.text}")

    if not os.path.exists(dest):
        os.makedirs(dest)

    with zipfile.ZipFile(io.BytesIO(response.content)) as zip_ref:
        zip_ref.extractall(dest)
        top_folder = zip_ref.namelist()[0].split("/")[0]
        extracted_path = os.path.join(dest, top_folder)
        return extracted_path