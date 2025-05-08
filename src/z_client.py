import socket
import json
import time
from messageType import MessageType

def request_node_status(server_address: tuple[str, int]):
    """
    Function to request the status of the node infinitely.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while True:
            # Create the message to request the node status
            data = {
                "cmd": MessageType.STAT.name
            }

            # Serialize the data to JSON
            serialized = json.dumps(data).encode('utf-8')

            # Prepend the 2-byte header
            header = len(serialized).to_bytes(2, 'big')
            to_send = header + serialized

            # Send the data via UDP
            sock.sendto(to_send, server_address)
            print(f"Sent status request to {server_address}")

            # Wait for the response
            try:
                response, addr = sock.recvfrom(4096)  # Buffer size of 4096 bytes
                print(f"Received response from {addr}: {response.decode('utf-8')}")
            except socket.timeout:
                print("No response received. Retrying...")

            # Sleep for 2 seconds before sending the next request
            time.sleep(2)

    except KeyboardInterrupt:
        print("Client stopped by user.")
    finally:
        sock.close()

if __name__ == "__main__":
    # Define the server address (IP and port)
    SERVER_IP = "127.0.0.1"
    SERVER_PORT = 8111

    # Set the server address
    server_address = (SERVER_IP, SERVER_PORT)

    # Start requesting node status
    request_node_status(server_address)
