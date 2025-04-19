import subprocess
import os
import argparse
import time

newNetwork = False

def build_image() ->None :
    """
    creates docker image based on docker/Dockerfile
    """
    print("Building Docker image...")
    subprocess.run([
        "docker", "build", "-f", "docker/Dockerfile", "-t", "python13-node", "."
    ], check=True)
    print("Docker image built successfully.")

def start_containers(n:int) -> None:
    """
    :param n: amount of containers to create
    :return:
    """
    global newNetwork

    for index in range(n):
        container_name = f"container{index + 1}"
        port = f"800{index + 1}"
        print(f"Starting container {container_name}...")

        subprocess.run([
            "docker", "run", "--rm", "-d","--network", "host", "--name", container_name,
            "-p", f"{port}:8000",
            "-v", f"{os.getcwd()}/app:/app",
            "-e", f"PORT={port}",
            "-e",f"FIRST={newNetwork}",
            "python13-node"
        ], check=True)
        newNetwork = False
        print(f"Container {container_name} started.")
        time.sleep(0.5)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Docker image and start containers.")

    parser.add_argument(
        '-n', '--num-containers',
        type=int,
        default=3,
        help="Number of containers to start (default: 3)"
    )

    parser.add_argument(
        '-s', '--start-network',
        action='store_true',
        help="Flag to start network containers (default: False)"
    )

    args = parser.parse_args()

    if args.start_network:
        newNetwork = True
        print("Starting a new network")

    # docker calls
    build_image()
    start_containers(args.num_containers)

