import os
import asyncio
import tempfile
import logging
import shutil
import zipfile
import urllib.request
from typing import Optional, Dict
import requests
import re

def remove_directory( path: str):
    """Remove a directory and all its contents"""
    import shutil
    shutil.rmtree(path, ignore_errors=True)
    
def download_zip(url):
    response = requests.get(url, stream=True)
    if response.status_code == 200:
        content_disp = response.headers.get('Content-Disposition', '')
        match = re.search(r'filename="?([^"]+)"?', content_disp)
        filename = match.group(1) if match else 'downloaded_file.zip'
        with open(filename, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        return filename
    else:
        return None
        
def extract_zip_to_current_dir(zip_path):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall("./")

async def download_github_repo(url: str, token: str, target_dir_name:str) -> Optional[str]:
    " download a github repository"
    logging.info(f"Downloading {url}")

    try:
            # validate url
            if not url.startswith("https://github.com/"):
                logging.error(f"Invalid GitHub URL: {url}")
                return None

            url = url.rstrip("/")
            parts = url.replace("https://github.com/", "").split("/")

            # validate url agaiun :^)
            if len(parts) < 2 or len(parts) > 3:
                logging.error(f"Invalid GitHub URL: {url}")
                return None

            # get usr and repo
            user, repo = parts[0], parts[1]

            if not user or not repo:
                return None

            # prepare message
            zip_url = f"https://api.github.com/repos/{user}/{repo}/zipball"
            headers = {
                    "Authorization": f"token {token}" if token else None,
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28"
            }

            # remove none
            headers = {k: v for k, v in headers.items() if v is not None}

            loop = asyncio.get_event_loop()
            zip_path = await loop.run_in_executor(
                        None,
                        lambda: _download_file(zip_url, headers)
                    )

            # validate if the file was downloaded
            if not zip_path:
                logging.error(f"Failed to download {url}")
                return None

            # extract the zip file
            extract_dir = await loop.run_in_executor(
                        None,
                        lambda: _extract_zip(zip_path)
                    )
            # clean up temp zip file
            os.unlink(zip_path)

            if extract_dir is None:
                logging.error(f"Failed to extract {zip_path}")
                return None

            # move file
            extracted_contents = os.listdir(extract_dir)
            if not extracted_contents:
                logging.error("Extracted directory is empty")
                return None

            repo_dir = os.path.join(extract_dir, extracted_contents[0])
            target_dir = os.path.join(os.getcwd(), target_dir_name)

            # If target already exists dont unzip
            if os.path.exists(target_dir):
                logging.info(f"Target directory {target_dir} already exists")
                shutil.rmtree(extract_dir, ignore_errors=True)
                return target_dir

            # Move the repo directory to the target
            shutil.move(repo_dir, target_dir)

            # Clean up the temp directory
            shutil.rmtree(extract_dir)
            logging.info(f"Removed temp directory {extract_dir}")
            logging.info(f"Downloaded and extracted {url} to {target_dir}")
            return repo

    except Exception as e:
        logging.error(f"Error downloading GitHub repository: {e}")
        return None

def _download_file(url:str, headers: Dict = None) -> Optional[str]:
    "downloads a file from the given url"
    try:
        # create temp file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.close()
            # download the file
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as response, open(temp_file.name, 'wb') as out_file:
                shutil.copyfileobj(response, out_file)
            return temp_file.name
    except Exception as e:
        logging.error(f"Error downloading file: {e}")
        return None

def _extract_zip(zip_path: str) -> Optional[str]:
    "extracts the zip file"
    try:
        # Create a temp dir but don't use context manager so it doesn't auto-delete
        temp_dir = tempfile.mkdtemp()
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
            return temp_dir
        except Exception as e:
            # If extraction fails, clean up the directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            logging.error(f"Error extracting zip file: {e}")
            return None
    except Exception as e:
        logging.error(f"Error creating temporary directory: {e}")
        return None

def folder2zip(path:str)-> str:
    "creates a zip file from the current directory"
    try:
        # check if path is a directory
        abs_path = os.path.abspath(path)
        if not os.path.isdir(abs_path):
            logging.error(f"Path {path} is not a directory")
            return None

        # create zip path
        import uuid
        folder_name = os.path.basename(abs_path.rstrip(os.sep))
        zip_filename = f"{folder_name}_{uuid.uuid4().hex[:8]}.zip"
        zip_path = os.path.join(os.getcwd(), zip_filename)

        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(abs_path):
                    dirs[:] = [d for d in dirs if 'cache' not in d.lower()]
                    for file in files:
                        if 'cache' in file.lower():
                            continue
                        file_path = os.path.join(root, file)

                        # Preserve the top-level folder in the archive
                        arcname = os.path.join(
                            folder_name,
                            os.path.relpath(file_path, abs_path)
                        )
                        zipf.write(file_path, arcname)
            return zip_path
        except Exception as e:
            logging.error(f"Failed to zip folder {abs_path}: {e}")
            return None

    except Exception as e:
        logging.error(f"Error creating zip file: {e}")
        return None
