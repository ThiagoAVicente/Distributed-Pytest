import asyncio
from network.message import Message, MessageType
from network.protocol import AsyncProtocol
from typing import Dict, Set, List
import logging
import time
import random

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

CHECK_DEAD_NODES_INTERVAL:float = 15
MAX_DEAD_TRIES = 3

def generate_id():
    """
    gen a "unique" id
    """
    timestamp = int(time.time() * 1e6)
    rand = random.randint(10000, 99999)
    return int(f"{timestamp}{rand}")

class Network:

    """
    NetworkFacade is a class that handles the network communication for the node.
    It uses the AsyncProtocol class to send and receive messages.
    Implements a mesh network topology.
    """

    def __init__(self,addr:tuple[str,int],start:bool = False):
        self.run:bool = False
        self.node_addr:tuple[str,int] = addr
        self.protocol:AsyncProtocol = None # type: ignore
        self.peers:Dict[str,tuple[str,int]] = {}
        self.node_id:str = str(generate_id()) if start else None # type: ignore
        self.discovery_task:asyncio.Task = None # type: ignore

        # recover from network failures
        self.dead_peers:Dict[str,List] = {}
        self.last_dead_check:float = 0.0

    async def start(self) :
        self.protocol = await AsyncProtocol.create(self.node_addr)

    async def stop(self):
        if self.protocol is not None:
            self.protocol = None
        else:
            logging.warning("Protocol is already closed or not initialized.")

        # cancel the sicovery server if it exists
        if self.discovery_task is not None:
            self.discovery_task.cancel()
            self.discovery_task = None

    def is_running(self) -> bool:
        return self.protocol is not None

    def add_peer(self, id:str, addr:tuple[str,int]) -> None:
        """
        add a peer to the list of peers
        """
        if id not in self.peers:
            self.peers[id] = addr
            logging.info(f"Added peer {id} to the list of peers")

    def remove_peer(self, id:str) -> None:
        """
        remove a peer from the list of peers
        """
        if id in self.peers:
            addr = self.peers[id]
            self.dead_peers[id] = [addr,0]
            del self.peers[id]
            logging.info(f"Removed peer {id} from the list of peers")


    def CONNECT_REP(self,addr:tuple[str,int]) ->str:
        """
        send a connect response to the discovery server
        """

        # Verificar se o endereço já existe nos peers
        old_node_id = None
        for node_id, peer_addr in list(self.peers.items()):
            if peer_addr == addr:
                old_node_id = node_id
                break

        new_id = str(generate_id())

        # Se encontrou um nó existente com mesmo IP:porta, remova-o
        if old_node_id:
            logging.info(f"Peer with address {addr} already exists with ID {old_node_id}. ")
            del self.peers[old_node_id]
            new_id = old_node_id # keeping the same id

        # Se o endereço não existir, prosseguir com a conexão normal
        while new_id in self.peers:
            new_id = str(generate_id())

        mssg = Message(
            MessageType.CONNECT_REP,
            {"peers": self.peers.copy(), "id": self.node_id, "given_id": new_id},
        )
        self.peers[new_id] = addr
        self.protocol.send(mssg.to_dict(), addr)

        return new_id

    async def connect(self,haddr:tuple):
        """
        Connects to a network by sending a message to the discovery server
        """
        logging.info(f"Connecting {self.node_addr} to a network in {haddr}")

        while 1:

            # contact the discovery server via udp broadcast
            mssg = Message(
                MessageType.CONNECT,
                {},
            )
            self.protocol.send(mssg.to_dict(), haddr )

            # wait for a response
            try:
                response = await asyncio.wait_for(self.protocol.recv(), timeout=5)

                if response is not None:
                    data, _ = response
                    if data.get("cmd") == MessageType.CONNECT_REP.name:
                        # update the peers list
                        self.peers = {node_id: tuple(addr) for node_id, addr in data["data"]["peers"].items() if addr[0] != self.node_addr[0] and addr[1] != self.node_addr[1]}
                        addr = (data["ip"], int(data["port"]))
                        self.add_peer(data["data"]["id"], addr)
                        self.node_id = data["data"]["given_id"]
                        logging.info(f"Connected to {addr} with peers {self.peers}")
                        break

            except asyncio.TimeoutError:
                logging.warning("No response from discovery server")

            await asyncio.sleep(1)

    def merge_peers(self,p:Dict, excluded:Set[str] ):

        # create sets to avoid duplicates
        s = set(self.peers.keys())
        s = s.union(set(p.keys()))
        new_peers = {}

        #logging.warning(f"Merging peers: {s} with excluded: {excluded}")

        for node_id in s:

            # skip this node entry
            if node_id == self.node_id:
               continue
            if node_id in excluded and not(node_id in self.dead_peers):
                addr = self.peers.get(node_id, p.get(node_id))
                self.dead_peers[node_id] = [addr,0]
                continue

            if node_id in self.peers:
                new_peers[node_id] = tuple(self.peers[node_id])
            else:
                new_peers[node_id] = tuple(p[node_id])

            # remove node from dead peers if it exists
            if node_id in self.dead_peers:
                del self.dead_peers[node_id]

        self.peers = new_peers

    def get_peers_ip(self) -> list[str]:
        """
        returns the list of peers ip addresses and port on format "ip:port"
        """
        return [f"{peer[0]}:{peer[1]}" for peer in self.peers.values()]

    def get_peers(self) -> Dict:
        """return a copy of the peers dictionary"""
        return self.peers.copy()

    async def recv(self) -> tuple[Dict,tuple[str,int]]:
        return await self.protocol.recv()

    def heartbeat2dead(self,mssg):

        # check if there are dead peers
        if len(self.dead_peers.keys()) == 0:
            return

        # check if there is the time to check dead peers
        if time.time() - self.last_dead_check < CHECK_DEAD_NODES_INTERVAL:
            return

        to_remove = []
        for dead_id,dead_peer_entry in self.dead_peers.items():
            self.protocol.send(mssg.to_dict(), dead_peer_entry[0])

            times = dead_peer_entry[1] + 1
            if times >= MAX_DEAD_TRIES:
                logging.warning(f"Peer {dead_peer_entry[0]} is dead, removing from the list of peers")
                to_remove.append(dead_id)
                continue

            # update the dead peer entry
            self.dead_peers[dead_id][1] = times

        for id in to_remove:
            del self.dead_peers[id]

        self.last_dead_check = time.time()

    def heartbeat(self,data:dict) -> None:

        mssg = Message(
        MessageType.HEARTBEAT,
        data,
        )
        self.__send_to_all(mssg)
        self.heartbeat2dead(mssg)

    def task_announce(self) -> None:
        """
        announce a new project to the network
        """
        mssg = Message(
            MessageType.TASK_ANNOUNCE,
            {"id":self.node_id},
        )
        self.__send_to_all(mssg)

    def task_request(self, addr:tuple[str,int]) -> None:
        """
        request a task from the anouncer
        """
        mssg = Message(
            MessageType.TASK_REQUEST,
            {"id":self.node_id},
        )
        self.protocol.send(mssg.to_dict(), addr)

    def task_send(self,addr:tuple, info:dict) -> None:
        """
        send a task to the requester
        """
        mssg = Message(
            MessageType.TASK_SEND,
            {"id":self.node_id, "info": info},
        )
        self.protocol.send(mssg.to_dict(), addr)

    def task_confirm(self, addr:tuple, content:Dict) -> None:
        """
        confirm a task to the requester
        """
        mssg = Message(
            MessageType.TASK_CONFIRM,
            content,
        )
        self.protocol.send(mssg.to_dict(), addr)

    def cache_update(self, cache:Dict)->None:
        """
        send cache to all peers
        """
        mssg = Message(
            MessageType.CACHE_UPDATE,
            cache,
        )
        self.__send_to_all(mssg)

    def project_announce(self,info:Dict)->None:
        """
        send project anounce to all peers
        """
        mssg = Message(
            MessageType.PROJECT_ANNOUNCE,
            info,
        )
        self.__send_to_all(mssg)


    def recovery_election(self, data:Dict)->None:
        """
        Anuncia candidatura para eleição de recuperação
        """

        mssg = Message(
            MessageType.RECOVERY_ELECTION,
            data,
        )
        self.__send_to_all(mssg)

    def recovery_election_rep(self, addr, data:Dict)-> None:
        """
        Responde a uma eleição de recuperação
        """
        mssg = Message(
            MessageType.RECOVERY_ELECTION_REP,
            data,
        )

        # send to node
        self.protocol.send(mssg.to_dict(), addr)

    def recovery_election_result(self,addr, data:Dict)->None:
        """
        Anuncia o resultado da eleição de recuperação
        """
        mssg = Message(
            MessageType.RECOVERY_ELECTION_RESULT,
            data,
        )
        self.protocol.send(mssg.to_dict(), addr)

    def evaluation_responsibility_update(self, data:Dict)->None:
        """
        Anuncia que um nó assumiu responsabilidade por um projeto
        """
        mssg = Message(
            MessageType.EVALUATION_RESPONSIBILITY_UPDATE,
            data,
        )
        self.__send_to_all(mssg)

    def __send_to_all(self, mssg:Message) -> None:
        """
        send a message to all peers
        """
        for peer in self.peers.values():
            self.protocol.send(mssg.to_dict(), peer)
