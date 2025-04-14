import json
import pickle
from socket import socket
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from socket import socket


class CDProto:
    """Protocolo de comunicação PubSub"""

    HEADER_SIZE = 2 # 2 bytes para o tamanho


    @classmethod
    def send(cls, conn: socket, data: Dict[str, Any]) -> bool:
        """Envia dados através da conexão"""
        try:

            #Serializa para JSON
            serialized = json.dumps(data).encode('utf-8')
            sz = len(serialized)

            # Monta header: 2 bytes tamanho + 1 byte serializer
            header = sz.to_bytes(2, 'big')
            toSend = header + serialized

            
            #Envia
            conn.sendall(toSend)
            return True

        except Exception as e:
            print(f"Send error: {e}")
            return False



    @classmethod
    def recv(cls, conn: socket) -> Optional[Dict[str, Any]]:
        """Recebe e desserializa dados da conexão"""
        try:
            # Lê os 2 bytes do header
            header = conn.recv(cls.HEADER_SIZE)
            if len(header) != cls.HEADER_SIZE:
                raise CDProtoBadFormat()

            # Extrai o tamanho dos dados (primeiros 2 bytes)
            size = int.from_bytes(header, 'big')

            # Lê o corpo da mensagem
            data = b''
            while len(data) < size:
                chunk = conn.recv(min(size - len(data), 4096))  # Lê em chunks
                if not chunk:
                    raise ConnectionError("Conexão fechada durante a leitura")
                data += chunk

            # Desserializa 
            message = json.loads(data.decode('utf-8'))
            
            return message

        except json.JSONDecodeError as e:
            raise CDProtoBadFormat(data) from e

        except Exception as e:
            return None


    


class CDProtoBadFormat(Exception):
    """Exception when source message is not CDProto."""
    def __init__(self, original_msg: bytes = None):
        self._original = original_msg

    @property
    def original_msg(self) -> str:
        return self._original.decode("utf-8") if self._original else ""

