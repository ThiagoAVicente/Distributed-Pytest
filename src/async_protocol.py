import asyncio
import json
from typing import Any, Dict, Optional, Tuple

class CDProto:
    """
    defines encode and decode methods for the protocol
    """
    
    HEADER_SIZE = 2
    
    @classmethod 
    def _encode(cls,data:Dict[str,Any]) -> bytes:
        """
        encodes data to json
        :data : dict data to be serialized
        :return : bytes header + serialized data
        """
        
        # serialize data
        serialized:bytes = json.dumps(data).encode('utf-8')
        
        # prepare header
        size:int = len(serialized)
        header:bytes = size.to_bytes(cls.HEADER_SIZE, 'big')
        
        return header + serialized
        
    @classmethod
    def _decode(cls,packet:bytes) -> Dict[str,Any]:
        """
        decodes data from json
        :packet : bytes data to be deserialized
        :return : dict deserialized data
        """
        
        # ensure packet is long enough
        if len(packet) < cls.HEADER_SIZE:
            raise CDProtoBadFormat(packet)
        
        # read packet
        size:int = int.from_bytes(packet[:cls.HEADER_SIZE], 'big')
        body:bytes = packet[cls.HEADER_SIZE:cls.HEADER_SIZE + size]
        
        return json.loads(body.decode('utf-8'))
        
class AsyncProtocol(asyncio.DatagramProtocol):
    
    """
    protocol for async socket communication.
    EACH NODE SHOULD HAVE ITS OWN INSTANCE OF THIS CLASS
    """
    
    ###### interface methods ########
    def __init__(self):
        self._recv_queue = asyncio.Queue()
        self.transport = None
    
    def connection_made(self, transport):
        self.transport = transport # udp transport
    
    def datagram_received(self, data: bytes, addr: Tuple[str, int]): # callback method
        """
        callback method that is called when data is received
        """
        try:
            message = CDProto._decode(data)
            # store message in the queue
            self._recv_queue.put_nowait((message, addr))
                
        except Exception as e:
            print(f"Error decoding message: {e}")
    ################################
    
    async def recv(self) -> tuple[Dict,tuple[str,int]]:
        """
        receives data from the queue
        :return : dict deserialized data
        """
        
        # retrive data from queue
        message, addr = await self._recv_queue.get()
        
        return message, addr
    
    def close(self):
        # close transport
        if self.transport:
            self.transport.close()
            
    def send(self,data:dict,target_addr:tuple[str,int]):
        """
        send data to target
        """
        
        # ensure protocol has started
        if not self.transport:
            raise RuntimeError("Transport is not initialized. Ensure the protocol is started.")
                
        # encode
        packet:bytes = CDProto._encode(data)
        
        # send data
        self.transport.sendto(packet, target_addr)
             
    @classmethod
    async def create(cls,addr:tuple[str,int]) -> "AsyncProtocol":
        """
        create an instance of the protocol using the provided address
        """
        loop = asyncio.get_running_loop()
        protocol = cls()                            # create an async protocol instance
        
        # create udp socket
        await loop.create_datagram_endpoint(
            lambda: protocol,                       # set protocol to handle the communication
            local_addr=addr                         # sbind sokcetaddress
        )
        
        return protocol                           

class CDProtoBadFormat(Exception):
    """Exception when source message is not CDProto."""
    def __init__(self, original_msg: bytes = None):
        self._original = original_msg

    @property
    def original_msg(self) -> str:
        return self._original.decode("utf-8") if self._original else ""