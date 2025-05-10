import os
import asyncio
import tempfile
import logging
import shutil
import zipfile
import urllib.request
from typing import Optional, Dict

async def download_github_repo(url: str, token: str = None, eval_id:str = "downloaded") -> bool:
    " download a github repository"
    logging.info(f"Downloading {url} to {eval_id}")
    
    try:
        
        # validate url
        if not url.startswith("https://github.com/"):
            logging.error(f"Invalid GitHub URL: {url}")
            return False
            
        url = url.rstrip("/")
        parts = url.replace("https://github.com/", "").split("/")
        
        # validate url agaiun :^)
        if len(parts) < 2 or len(parts) > 3:
            logging.error(f"Invalid GitHub URL: {url}")
            return False
        
        # get usr and repo
        user, repo = parts[0], parts[1]
        
        if not user or not repo:
            return False
            
        # prepare message
        zip_url = f"https://api.github.com/repos/{user}/{repo}/zipball"
        headers = {
                "Authorization": f"token {token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28"
        }
        
        loop = asyncio.get_event_loop()
        zip_path = await loop.run_in_executor(
                    None, 
                    lambda: _download_file(zip_url,headers)
                )
        
        # validade if the file was downloaded
        if not zip_path:
            logging.error(f"Failed to download {url}")
            return False
            
        # extract the zip file
        extract_dir = await loop.run_in_executor(
                    None,
                    lambda: _extract_zip(zip_path)
                )
        if extract_dir is None:
            logging.error(f"Failed to extract {zip_path}")
            return False
            
        # clean up temp zip file
        os.unlink(zip_path)

        # move the extracted directory to the final location
        final_path = os.path.join(os.getcwd(), eval_id)

        # check ifpath already exists
        if os.path.exists(final_path):
            if os.path.isdir(final_path):
                shutil.rmtree(final_path)
            else:
                os.remove(final_path)

        extracted_contents:list[str] = os.listdir(extract_dir)
        
        if len(extracted_contents) == 1 and os.path.isdir(os.path.join(extract_dir, extracted_contents[0])):
            # zip has a folder with the project
            source_dir = os.path.join(extract_dir, extracted_contents[0])
            # Ensure parent directory exists
            os.makedirs(os.path.dirname(final_path), exist_ok=True)
            shutil.copytree(source_dir, final_path)
            shutil.rmtree(extract_dir, ignore_errors=True)
        else:
            # zip has no folder, just files
            if not os.path.exists(final_path):
                os.makedirs(final_path)
            for item in extracted_contents:
                source_item = os.path.join(extract_dir, item)
                dest_item = os.path.join(final_path, item)
                if os.path.isdir(source_item):
                    shutil.copytree(source_item, dest_item)
                else:
                    shutil.copy2(source_item, dest_item)
            shutil.rmtree(extract_dir, ignore_errors=True)
            
        return True
            
    except Exception as e:
            logging.error(f"Error downloading GitHub repository: {e}")
            return False
        
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
        