import socket
import json
import argparse


def main(token:str,url:str):
    data = {
        "cmd": "evaluation",
        "type":"url",
        "url": f"{url}",
        "token": f"{token}"
    }

    # Serialize the data to JSON
    serialized = json.dumps(data).encode('utf-8')

    # Prepend the 2-byte header
    header = len(serialized).to_bytes(2, 'big')
    to_send = header + serialized

    # Send the data via UDP
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(to_send, ("192.168.0.3", 8111))
    sock.close()

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Send data via UDP.")
    parser.add_argument("token", type=str, help="GitHub token")
    parser.add_argument("url", type=str, help="GitHub URL")

    args = parser.parse_args()

    main(args.token, args.url)
