import subprocess
import os
import argparse

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
    for index in range(n):
        container_name = f"container{index + 1}"
        port = f"800{index + 1}"
        print(f"Starting container {container_name}...")

        subprocess.run([
            "docker", "run", "--rm", "-d", "--name", container_name,
            "-p", f"{port}:8000",
            "-v", f"{os.getcwd()}/app:/app",
            "-e", f"PORT={port}",
            "python13-node"
        ], check=True)

        print(f"Container {container_name} started.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build Docker image and start containers.")

    parser.add_argument(
        '-n', '--num-containers',
        type=int,
        default=3,
        help="Number of containers to start (default: 3)"
    )

    args = parser.parse_args()

    # docker calls
    build_image()
    start_containers(args.num_containers)

