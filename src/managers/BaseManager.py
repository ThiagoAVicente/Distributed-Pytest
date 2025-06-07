from abc import ABC, abstractmethod

class BaseManager(ABC):
    def __init__(self, node_context):
        self.node_context = node_context
    
    @abstractmethod
    async def start(self):
        pass
    
    @abstractmethod
    async def stop(self):
        pass
