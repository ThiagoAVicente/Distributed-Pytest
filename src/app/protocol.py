import json
import logging
import pickle
from socket import socket
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import socket as s


class CDProto:
    """Protocolo de comunicação PubSub"""

    HEADER_SIZE = 2 # 2 bytes para o tamanho

    @classmethod
    def brodCast(cls, sock:s.socket, data: Dict[str,any]):

        sock.setsockopt(s.SOL_SOCKET, s.SO_BROADCAST, 1)

    @classmethod
    def send(cls, sock: s.socket, addr: Tuple[str, int], data: Dict[str, Any]) -> bool:
        """Envia dados via UDP"""
        try:
            serialized = json.dumps(data).encode('utf-8')
            sz = len(serialized)

            header = sz.to_bytes(2, 'big')
            toSend = header + serialized

            sock.sendto(toSend, addr)
            return True

        except Exception as e:
            print(f"Send error: {e}")
            return False

    @classmethod
    def recv(cls, sock: s.socket) -> Optional[Tuple[Dict[str, Any], Tuple[str, int]]]:
        """Recebe dados via UDP"""
        try:
            # Lê header + corpo numa só chamada
            packet, addr = sock.recvfrom(4096)
            if len(packet) < cls.HEADER_SIZE:
                return None

            size = int.from_bytes(packet[:cls.HEADER_SIZE], 'big')
            data = packet[cls.HEADER_SIZE:cls.HEADER_SIZE + size]

            message = json.loads(data.decode('utf-8'))

            return message, addr

        except json.JSONDecodeError as e:
            print("Decoding error:", e)
            return None

        except Exception as e:
            print("Recv error:", e)
            return None



class CDProtoBadFormat(Exception):
    """Exception when source message is not CDProto."""
    def __init__(self, original_msg: bytes = None):
        self._original = original_msg

    @property
    def original_msg(self) -> str:
        return self._original.decode("utf-8") if self._original else ""

