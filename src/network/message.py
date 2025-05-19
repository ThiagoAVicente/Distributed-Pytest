
import enum

class MessageType(enum.Enum):
    CACHE_UPDATE = 0
    HEARTBEAT = 1
    CONNECT = 2
    CONNECT_REP = 3
    
    TASK_ANNOUNCE = 4
    TASK_REQUEST = 5
    TASK_SEND = 6
    TASK_WORKING = 7
    TASK_RESULT = 8
    
    TASK_CONFIRM = 9
    TASK_RESULT_REP = 10

    PROJECT_ANNOUNCE = 11

        
        
    
    
    
    

class Message:
    def __init__(self, msg_type: MessageType, data: dict, ip:str, port:int):
        self.msg_type:MessageType = msg_type
        self.data:dict = data
        self.ip:str = ip
        self.port:int = port

    def to_dict(self):
        return {
            "ip": self.ip,
            "port": self.port,
            "cmd": self.msg_type.name,
            "data": self.data
        }