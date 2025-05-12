from network.message import Message, MessageType
from network.protocol import AsyncProtocol
from typing import Dict

class NetworkFacade:
    
    def __init__(self,addr:tuple[str,int]):
        self.node_addr:tuple[str,int] = addr
        self.protocol:AsyncProtocol = None

    async def start(self):
        self.protocol = await AsyncProtocol.create(self.node_addr)
    
    def is_running(self) -> bool:
        return self.protocol is not None
        
    def HEARTBEAT(self,node_addr:tuple[str,int], status:str = "free") -> None:
        mssg = Message( MessageType.HEARTBEAT, {"status":status}) 
        self.protocol.send( mssg.to_dict(), node_addr)
        
    async def recv(self) -> tuple[Dict,tuple[str,int]]:
        
        return await self.protocol.recv()
        