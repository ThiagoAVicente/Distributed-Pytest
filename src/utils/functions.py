import os
import asyncio
import tempfile
import logging
import shutil
import io
import zipfile
import urllib.request
from typing import Optional, Dict

async def download_github_repo(url: str, token: str = None, eval_id:str = "downloaded") -> Optional[str]:
    " download a github repository"
    logging.info(f"Downloading {url} to {eval_id}")
    
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
            
            # Get absolute path for eval_id directory
            eval_dir = os.path.abspath(eval_id)
            
            # make eval_id directory if it doesn't exist
            if not os.path.exists(eval_dir):
                os.makedirs(eval_dir)
            
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
            target_dir = os.path.join(eval_dir, repo)
            
            # If target already exists, remove it
            if os.path.exists(target_dir):
                shutil.rmtree(target_dir)
                
            # Move the repo directory to the target
            shutil.move(repo_dir, target_dir)
            
            # Clean up the temp directory
            shutil.rmtree(extract_dir)
            
            return target_dir
                
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
        # create temp file
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.close()
            # create zip file
            with zipfile.ZipFile(temp_file.name, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, dirs, files in os.walk(os.getcwd()):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, os.getcwd())
                        zipf.write(file_path, arcname)
            return temp_file.name
    except Exception as e:
        logging.error(f"Error creating zip file: {e}")
        return None
        
def file2bytes(path:str)-> bytes:
    "converts a file to bytes"
    try:
        with open(path, 'rb') as f:
            return f.read()
    except Exception as e:
        logging.error(f"Error reading file: {e}")
        return None
        
async def folder_2_bytes(path: str) -> bytes:
    loop = asyncio.get_running_loop()
    # folder2zip 
    zip_path = await loop.run_in_executor(None, folder2zip, path)
    if not zip_path:
        return None
    # file2bytes
    file_bytes = await loop.run_in_executor(None, file2bytes, zip_path)
    
    # remove zip file
    os.unlink(zip_path)
    return file_bytes

async def bytes_2_folder(zip_bytes: bytes,target_dir:str = ".") -> bool:
    "extracs zip from bytes into folder"
    
    zip_stream = io.BytesIO(zip_bytes)
    
    try:
        with zipfile.ZipFile(zip_stream) as f:
            f.extractall(target_dir)
        return True
    except Exception as e:
        logging.error(f"Error extracting zip file from bytes: {e}")
        return False