
import enum

class MessageType(enum.Enum):
    HEARTBEAT = 1
    EVALUATION = 2
    EVALUATION_RESULT = 3
    EVALUATION_STATUS = 4
    

class Message:
    def __init__(self, msg_type: MessageType, data: dict):
        self.msg_type:MessageType = msg_type
        self.data:dict = data

    def to_dict(self):
        return {
            "cmd": self.msg_type.name,
            "data": self.data
        }