import asyncio
from network.message import Message, MessageType
from network.protocol import AsyncProtocol
from typing import Dict
import logging
from uuid import uuid4
import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class NetworkFacade:
    
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
        self.node_id:str = uuid4().hex if start else None # type: ignore
        self.discovery_task:asyncio.Task = None # type: ignore

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
        
    def CONNECT_REP(self,addr:tuple[str,int]) ->None:
        """
        send a connect response to the discovery server
        """
        new_id = uuid4().hex
        mssg = Message( 
            MessageType.CONNECT_REP, 
            {"peers": self.peers.copy(), "id": self.node_id, "given_id": new_id},
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.peers[new_id] = addr
        self.protocol.send(mssg.to_dict(), addr)
    
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
                os.environ.get("OUTSIDE_IP"),       #type: ignore
                int(os.environ.get("OUTSIDE_PORT")) #type: ignore
            )
            self.protocol.send(mssg.to_dict(), haddr )

            # wait for a response
            try:
                response = await asyncio.wait_for(self.protocol.recv(), timeout=5)
                
                if response is not None:
                    data, _ = response
                    if data.get("cmd") == MessageType.CONNECT_REP.name:
                        # update the peers list
                        self.peers = {node_id: tuple(addr) for node_id, addr in data["data"]["peers"].items() if tuple(addr) != self.node_addr} 
                        addr = (data["ip"], int(data["port"]))
                        self.peers[data["data"]["id"]] = addr
                        self.node_id = data["data"]["given_id"]
                        #logging.info(f"Connected to {addr} with peers {self.peers}")
                        break
            
            except asyncio.TimeoutError:
                logging.warning("No response from discovery server")
            
            await asyncio.sleep(1)
            
    async def set_peers(self, new_peers:Dict[str,tuple[str,int]]):
        """
        updates the list of peers
        """
        self.peers = new_peers
        
    async def add_peer(self, id:str, peer:tuple[str,int]):
        """
        adds a peer to the list of peers
        """
        if id not in self.peers:
            self.peers[id] = peer
            logging.info(f"Added peer {id} to the list of peers")
        else:
            logging.warning(f"Peer {id} already exists in the list of peers")
    
    def get_peers_ip(self) -> list[str]:
        """
        returns the list of peers ip addresses and port on format "ip:port"
        """
        return [f"{peer[0]}:{peer[1]}" for peer in self.peers.values()]
   
    async def recv(self) -> tuple[Dict,tuple[str,int]]:
        return await self.protocol.recv()
        
    def HEARTBEAT(self) -> None:
        mssg = Message( 
        MessageType.HEARTBEAT,
        {},
        os.environ.get("OUTSIDE_IP"),       #type: ignore
        int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.__send_to_all(mssg)
            
    def TASK_ANNOUNCE(self) -> None:
        """
        announce a new project to the network
        """
        mssg = Message(
            MessageType.TASK_ANNOUNCE, 
            {"id":self.node_id},
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.__send_to_all(mssg)
    
    def TASK_REQUEST(self, addr:tuple[str,int]) -> None:
        """
        request a task from the anouncer
        """
        mssg = Message(
            MessageType.TASK_REQUEST, 
            {"id":self.node_id},
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.protocol.send(mssg.to_dict(), addr)
        
    def TASK_SEND(self,addr:tuple, info:dict) -> None:
        """
        send a task to the requester
        """
        mssg = Message(
            MessageType.TASK_SEND, 
            {"id":self.node_id, "info": info},
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.protocol.send(mssg.to_dict(), addr)
    
    def TASK_CONFIRM(self, addr:tuple, content:Dict) -> None:
        """
        confirm a task to the requester
        """
        mssg = Message(
            MessageType.TASK_CONFIRM, 
            content,
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.protocol.send(mssg.to_dict(), addr)
    
    def TASK_RESULT(self, addr:tuple, result:dict) -> None:
        """
        send the result of a task to the requester
        """
        mssg = Message(
            MessageType.TASK_RESULT, 
            result,
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.protocol.send(mssg.to_dict(), addr)

    def TASK_RESULT_REP(self, addr:tuple, result:dict) -> None:
        """
        send the result of a task to the requester
        """
        mssg = Message(
            MessageType.TASK_RESULT_REP, 
            result,
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.protocol.send(mssg.to_dict(), addr)
        
    def CACHE_UPDATE(self, cache:Dict)->None:
        """
        send cache to all peers
        """
        mssg = Message(
            MessageType.CACHE_UPDATE, 
            cache,
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.__send_to_all(mssg)

    def PROJECT_ANNOUNCE(self,info:Dict)->None:
        """
        send project anounce to all peers
        """
        mssg = Message(
            MessageType.PROJECT_ANNOUNCE, 
            info,
            os.environ.get("OUTSIDE_IP"),       #type: ignore
            int(os.environ.get("OUTSIDE_PORT")) #type: ignore
        )
        self.__send_to_all(mssg)

    def __send_to_all(self, mssg:Message) -> None:
        """
        send a message to all peers
        """
        for peer in self.peers.values():
            self.protocol.send(mssg.to_dict(), peer)