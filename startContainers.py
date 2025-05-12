# docker run -d --name=node{i} -p 800{i}:800{i} cd_node
# 
import argparse

def docker_image_exists(image_name:str = "cd_node") -> bool:
    "check if docker image exists"
    import subprocess
    try:
        result = subprocess.run(["docker", "images", "-q", image_name], stdout=subprocess.PIPE)
        return len(result.stdout) > 0
    except Exception as e:
        print(f"Error checking docker image: {e}")
        return False
        

def main(new:bool = False, start_id:int = 0, amount:int = 4 ):
    
    # ensure image was created
    if not docker_image_exists():
        print("Docker image cd_node not found. Please build the image first.")
        return
        
    # start nodes
    import subprocess
    
    i:int = start_id - 1
    count:int = 0
    while count < amount:
    
        i += 1
        # check if container is already running
        result = subprocess.run(["docker", "ps", "-q", "-f", f"name=node{i}"], stdout=subprocess.PIPE)
        if len(result.stdout) > 0:
            print(f"Container node{i} is already running.")
            continue
        
        # start the container
        print(f"Starting container node{i}...")
        subprocess.run(["docker", "run","--rm", "-d", f"--name=node{i}", "-e", f"START={1 if new else 0}","-e",f"PORT_ID={i}", "-p", f"800{i}:800{i}", "cd_node"])
        
        
        count += 1
        
        if new :
            new = False
        
        
if __name__ == "__main__":
    
    # read agrs
    parser = argparse.ArgumentParser(description="Start CD Node containers")
    parser.add_argument("--new", action="store_true", help="Start new network")
    parser.add_argument("--start_id", type=int, default=0, help="Start ID for containers")
    parser.add_argument("--amount", type=int, default=4, help="Number of containers to start")
    
    args = parser.parse_args()
    
    # start containers
    main(new=args.new, start_id=args.start_id, amount=args.amount)