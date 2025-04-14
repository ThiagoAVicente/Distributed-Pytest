import socket
import os

class Node:

    def __init__(self):

        # get port that docker is using<
        self.port = os.getenv('PORT', '8000')

        # socket creation
        self.sock:socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.timeout:int = 3
        self.sock.settimeout(self.timeout)

    def run(self):
        self.sock.bind(('0.0.0.0', int(self.port)))
        # TODO connect nodes