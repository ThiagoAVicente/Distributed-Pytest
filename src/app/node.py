import socket
import os

from protocol import CDProto, CDProtoBadFormat

from myTypes import T
import threading
import time
import logging

DISCOVERY_PORT = 9876
BROADCAST_INTERVAL = 5
DISCOVERY_TIMEOUT = 10


logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class Node:

    def __init__(self):

        self.done = False

        # get port that docker is using
        self.port = os.getenv("PORT")
        self.connected = False

        ### TODO: remove and implement election
        if int(self.port) == 8001:
            self.connected = True
        ####

        self.ip = socket.gethostbyname(socket.gethostname())
        self.timeout:int = 3

        # socket creation
        self.sock:socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(self.timeout)

        self.peers = []

        self.lock = threading.Lock()

    def __thread_safe_append(self,other):
        with self.lock:
            self.peers.extend(other)


    def __broadcast_discovery(self):

        # create an udp socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # prepare mssg
        message = {
            "type": T.DISCOVERY.name,
            "ip": self.ip,
            "port": self.port,
        }

        # send message
        CDProto.send(sock, ('<broadcast>', DISCOVERY_PORT), message)
        sock.close()

    def __discovery_listen(self):

        # create socket
        temp_sock:socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        temp_sock.settimeout(self.timeout)
        temp_sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
        temp_sock.bind(('', DISCOVERY_PORT))

        # wait for discovery request
        while True:
            try:
                result = CDProto.recv(temp_sock)
                if result is None:
                    continue

                decoded_message, addr = result


                if decoded_message.get("type") == T.DISCOVERY.name:
                    response = {
                        "type": T.DISCOVERY_REP.name,
                        "ip": self.ip,
                        "port": self.port,
                        "peers": self.peers,
                    }
                    # logging.info(response)
                    CDProto.send(temp_sock, (decoded_message["ip"], int(decoded_message["port"])), response)
                    self.__thread_safe_append([addr])
                    logging.info(f"Discovery listener capture: {decoded_message['ip']} - {decoded_message['port']}")

            except socket.timeout:
                logging.info("Discovery listener timeout")
                continue
            except Exception as e:
                logging.error(f"Discovery listener error: {e}")


    def run(self):
        self.sock.bind(('0.0.0.0', int(self.port)))

        start_time = time.time()

        # join the network
        while not self.connected:
            self.__broadcast_discovery()

            time.sleep(2.5)

            result = CDProto.recv(self.sock)
            if result is not None:
                data, address = result
                cmd = data["type"]
                logging.info(data)
                if cmd == T.DISCOVERY_REP.name:

                    # add peers
                    to_add = data["peers"]
                    to_add.append(address)
                    self.__thread_safe_append(to_add)

                    self.connected = True


            if time.time() - start_time >= DISCOVERY_TIMEOUT and not self.connected:
                self.connected = True
                logging.info(
                    "🌟 No responses received within timeout. Starting a new network as the first node.")

        discovery_thread = threading.Thread(target=self.__discovery_listen, daemon=True)
        discovery_thread.start()
        logging.info("✅ Discovery listener thread started after connection")

        while not self.done:
            data = CDProto.recv(self.sock)
            if data is not None:
                # TODO
                logging.info(threading.enumerate())
                continue