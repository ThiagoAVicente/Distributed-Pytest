import uuid
import socket
import os
from typing import Optional, Dict, Set
from protocol import CDProto, CDProtoBadFormat
from myTypes import T
import threading
import time
import logging
import random

DISCOVERY_PORT = 9876
BROADCAST_INTERVAL = 5.
DISCOVERY_TIMEOUT = 10.
NOTIFY_INTERVAL = 2.
CENTER_TIMEOUT = 8.
ELECTION_TIMEOUT = float(os.getenv("ELECTION_TIMEOUT", "4.0"))  # Reduced for faster elections

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class Node:

    def __init__(self):
        # node vars
        self.done = False
        self.working = False
        self.startElection: bool = False
        self.connected = True if os.getenv("FIRST") == "True" else False
        self.is_center = self.connected
        self.lastNotify: float = -1
        self.id = uuid.uuid4().int if self.connected else None
        self.centerNodeId = None
        self.election_start = .0
        self.eId = None             # election ID
        self.eAddress = None        # election address

        # get ip and port
        self.ip = socket.gethostbyname(socket.gethostname())
        self.port = os.getenv("PORT", "8000")

        # Socket creation
        self.timeout: int = 3
        self.sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(self.timeout)

        # Network info
        self.center_node: Optional[tuple] = (self.ip, self.port) if self.is_center else None
        self.peers = []
        self.freeNodes: Set = set()
        self.nodesCheck: Optional[Dict] = None
        self.lastCenterCheck: Optional[float] = None

        # threading
        self.lock = threading.Lock()

    def __thread_safe_append(self, other):
        with self.lock:
            self.peers.extend(other)

    def __broadcast_discovery(self):
        # create udp socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.timeout)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        # prepare message
        message = {
            "type": T.DISCOVERY.name,
            "ip": self.ip,
            "port": self.port,
        }

        # Send message
        CDProto.send(sock, ('<broadcast>', DISCOVERY_PORT), message)
        sock.close()

    def __discovery_listen(self):
        # create socket
        temp_sock: socket.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        temp_sock.settimeout(self.timeout)
        temp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        temp_sock.bind(('', DISCOVERY_PORT))

        # wait for requests
        while True:
            try:
                result = CDProto.recv(temp_sock)
                if result is None:
                    continue

                decoded_message, _ = result

                if decoded_message.get("type") == T.DISCOVERY.name:
                    addr = (decoded_message["ip"], int(decoded_message["port"]))
                    logging.info(f"Discovery request from {addr}")
                    g_id: int = uuid.uuid4().int

                    # send reply
                    response = {
                        "type": T.DISCOVERY_REP.name,
                        "ip": self.ip,
                        "port": self.port,
                        "peers": self.peers,
                        "givenID": g_id,
                        "centerID": self.id
                    }
                    CDProto.send(temp_sock, (decoded_message["ip"], int(decoded_message["port"])), response)

                    self.__thread_safe_append([(addr[0], addr[1], g_id)])
                    logging.info(f"Discovery listener capture: {decoded_message['ip']}:{decoded_message['port']}")

            except socket.timeout:
                logging.info("Discovery listener timeout")
                continue
            except Exception as e:
                logging.error(f"Discovery listener error: {e}")

    def __create_discovery_thread(self):
        # thread for discovery listener
        discovery_thread = threading.Thread(target=self.__discovery_listen, daemon=True)
        discovery_thread.start()
        logging.info("Discovery listener thread started after connection")

    def __notify_peers(self, mssg):
        #message to all nodes
        for entry in self.peers:
            peer = (entry[0], entry[1])
            CDProto.send(self.sock, peer, mssg)

    def __election(self):
        self.election_start = time.time()
        self.eId = self.id
        self.eAddress = (self.ip, self.port)
        logging.info(f"Initiating election: Node ID {self.id}, Address {self.ip}:{self.port}")
        mssg = {"type": T.ELECTION.name}
        for entry in self.peers:
            if entry[2] > self.id:
                CDProto.send(self.sock, (entry[0], entry[1]), mssg)

    def run(self):
        self.sock.bind(('', int(self.port)))
        start_time = time.time()

        # join a network
        while not self.connected:
            self.__broadcast_discovery()
            time.sleep(2.5)
            result = CDProto.recv(self.sock)
            if result is not None:
                data, _ = result
                cmd = data["type"]
                if cmd == T.DISCOVERY_REP.name:
                    address = (data["ip"], int(data["port"]))
                    to_add = data["peers"]
                    self.center_node = address
                    self.__thread_safe_append(to_add)
                    self.id = data["givenID"]
                    logging.info(f"Received id: {self.id} ")
                    self.centerNodeId = data["centerID"]
                    self.connected = True
                    self.lastCenterCheck = time.time()

            if time.time() - start_time >= DISCOVERY_TIMEOUT and not self.connected:
                self.connected = True
                self.is_center = True
                logging.info("No responses received within timeout. Starting a new network as the first node.")

        if self.is_center:
            self.__create_discovery_thread()
            self.nodesCheck = {}

        while not self.done:
            # logging.debug(self.is_center)
            # periodic life checks
            if time.time() - self.lastNotify > NOTIFY_INTERVAL:
                if self.is_center:
                    mssg = {"type": T.HEARTBEAT.name, "id": self.id, "peers": self.peers}
                    self.__notify_peers(mssg)
                else:
                    st = "W" if self.working else "F"
                    mssg = {"type": T.HEARTBEAT.name, "id": self.id, "status": st}
                    logging.info("Notify center")
                    CDProto.send(self.sock, self.center_node, mssg)
                self.lastNotify = time.time()

            # stop election after timeout
            if self.startElection and self.election_start > .0 and time.time() - self.election_start > ELECTION_TIMEOUT:
                logging.info(f"Election complete: New center ID {self.eId}, Address {self.eAddress}")
                self.centerNodeId = self.eId
                self.center_node = (self.eAddress[0],int(self.eAddress[1]))
                self.is_center =  self.centerNodeId == self.id
                if self.is_center:
                    self.nodesCheck = {(p[0], p[1]): time.time() for p in self.peers}
                    self.__create_discovery_thread()
                mssg = {"type": T.MASTER.name, "id": self.eId, "ip": self.eAddress[0], "port": self.eAddress[1]}
                self.__notify_peers(mssg)

                # reset vars
                self.eId = None
                self.eAddress = None
                self.election_start = .0
                self.startElection = False

            # process messages
            result = CDProto.recv(self.sock)
            if result is not None:
                data, address = result
                cmd = data["type"]

                if cmd == T.HEARTBEAT.name:
                    logging.info(f"HeartBeat from {address}  ")
                    id_ = data["id"]
                    if not self.is_center:
                        if self.centerNodeId == id_:
                            self.lastCenterCheck = time.time()

                            # filter peers so node cannot message itself
                            own_tuple = (self.ip, int(self.port), self.id)
                            #logging.info(own_tuple)
                            self.peers = [peer for peer in data["peers"] if peer[2] != own_tuple[2]]
                            #logging.info(self.peers)

                            self.startElection = False
                            logging.info("Center is alive")
                    else:
                        self.nodesCheck[address] = time.time()
                        if data["status"] == "F":
                            self.freeNodes.add(address)
                        else:
                            self.freeNodes.discard(address)

                elif cmd == T.ELECTION.name:
                    mssg = {"type": T.ELECTION_REP.name, "id": self.id}
                    CDProto.send(self.sock, address, mssg)
                    logging.info(f"Responded to ELECTION from {address}")

                elif cmd == T.ELECTION_REP.name and self.startElection:
                    if data["id"] > self.eId:
                        self.eId = data["id"]
                        self.eAddress = address
                        self.startElection = False

                        # update time so it won't start a new election now
                        self.lastCenterCheck = time.time()

                        logging.info(f"Updated election to higher-ID node: {data['id']}")
                    else:
                        logging.info(f"Ignoring ELECTION_REP from lower-ID node: {data['id']}")

                elif cmd == T.MASTER.name:
                    new_id = data["id"]
                    logging.info(f"->{new_id}--{self.id}")
                    self.centerNodeId = new_id
                    self.center_node = (data["ip"], int(data["port"]))
                    self.is_center = (self.id == new_id)
                    self.startElection = False
                    self.election_start = .0
                    if self.is_center :
                        self.nodesCheck = { (p[0],p[1]):time.time() for p in self.peers }
                        self.__create_discovery_thread()
                    logging.info(f"Accepted new center: ID {new_id}, Address {data['ip']}:{data['port']}")

            # trigger election if center is dead
            if not self.is_center and time.time() - self.lastCenterCheck > CENTER_TIMEOUT and not self.startElection:
                time.sleep(random.uniform(0, 1))  # Random backoff
                if not self.startElection:  # Recheck to avoid race conditions
                    logging.info("Didn't receive livecheck from center. Starting election")
                    self.startElection = True
                    self.__election()