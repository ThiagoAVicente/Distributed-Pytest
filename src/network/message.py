
import enum
import time
import os
import socket

def getIp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Connect to an external server to determine the outgoing IP
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        return ip
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()

class MessageType(enum.Enum):
    CACHE_UPDATE = 0
    HEARTBEAT = 1
    CONNECT = 2
    CONNECT_REP = 3
    TASK_ANNOUNCE = 4
    TASK_REQUEST = 5
    TASK_SEND = 6
    TASK_CONFIRM = 9
    PROJECT_ANNOUNCE = 11
    RECOVERY_ELECTION = 12                 # Eleição para recuperação
    RECOVERY_ELECTION_REP = 14
    EVALUATION_RESPONSIBILITY_UPDATE = 13  # Atualização de responsabilidade por Evaluation
    RECOVERY_ELECTION_RESULT = 15         # Resultado da eleição de recuperação

class Message:
    def __init__(self, msg_type: MessageType, data: dict):
        self.msg_type:MessageType = msg_type
        self.data:dict = data
        self.ip = os.environ.get("OUTSIDE_IP",getIp())
        self.port = int(os.environ.get("OUTSIDE_PORT",8000))

    def to_dict(self):
        return {
            "ip": self.ip,
            "port": self.port,
            "cmd": self.msg_type.name,
            "data": self.data,
            "timestamp": time.time()
        }
