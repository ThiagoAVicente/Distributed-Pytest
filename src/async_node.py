import asyncio
from typing import Optional
from async_protocol import AsyncProtocol
from messageType import MessageType
import functions as func

import logging

SLEEPTIME = 0.1

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


def getIp() -> str:
    
    return "127.0.0.1"
    "returns tje pc current ip address"
    import socket
    hostname = socket.gethostname()
    ip_address = socket.gethostbyname(hostname)
    return ip_address

class Node:

    def __init__(self,port:int):

        self.addr = (getIp(),port)
        self.protocol = None

        # pytest variables
        self.projectQueue:asyncio.Queue = asyncio.Queue()
        self.current_project:Optional[str] = None

        # counters
        self.total_passed:int = 0
        self.module_count:int = 0
        self.total_failed:int = 0
        self.project_count:int = 0
        self.evaluation_counter:int = 0

    """
    starts the node communication protocol
    """
    async def start(self):
        
        # create communication protocol (udp)
        self.protocol = await AsyncProtocol.create(self.addr)
        logging.info(f"Node started at {self.addr}")

    async def send_message(self, message:dict, target_addr:tuple[str,int]):
        """
        send message through the protocol
        """
        
        # ensure start() was called
        if self.protocol:
            self.protocol.send(message, target_addr)
        else:
            raise RuntimeError("Protocol not started. use start() 1st")

    """
    defines the node listen loop
    """
    async def listen(self):


        # ensure start() was called
        if not self.protocol:
            raise RuntimeError("Protocol not started. use start() 1st")

        logging.info(f"Listening on {self.addr}")
        
        while True:
            try:
                # retrieve message from queue
                message, addr = await self.protocol.recv()
                logging.info(f"Received message from {addr} -- {message}")

                # process the message
                await self.process_message(message,addr)

            except asyncio.CancelledError:
                # loop canceled
                break
            
            finally:
                await asyncio.sleep(SLEEPTIME)

    """
    function to process messages
    """
    async def process_message(self, message:dict, addr:tuple[str,int]):
        cmd = message.get("cmd")

        if cmd == MessageType.EVALUATION.name:
            
            self.evaluation_counter += 1
            
            type = message.get("type")

            if type == "url":
                url= message.get("url")
                token= message.get("token")

                try:
                    if url and token:
                        logging.info(f"Received URL: {url} with token: {token}")

                        project_path:str = await func.downloadFromGithub(token,url)
                        res:bool = await func.verifyFolder(project_path)
                                                
                        if not res:
                            await func.removeDir(project_path)
                            return
                        
                        # add project to the queue
                        await self.projectQueue.put(project_path)

                except Exception as e:
                    logging.error(f"Error processing URL: {e}")
                    await asyncio.sleep(SLEEPTIME)

            elif type == "zip":
                pass
        
        elif cmd == MessageType.STAT.name:
            data = {
                "all": {
                    "failed": self.total_failed,
                    "passed": self.total_passed,
                    "projects": self.project_count,
                    "evaluations": self.evaluation_counter,
                },
                # TODO : add each node info
            }
            # send data
            await self.send_message({"cmd":MessageType.STAT_REP.name,"data": data},addr)
                
        # TODO: add cmds
        else:
            logging.warning(f"Unknown command received: {cmd}")

    """
    loop to process projects
    """
    async def process_projects(self):
        """
        async function to processes projects
        """
        while True:
            # wait for a new project
            self.current_project = await self.projectQueue.get()
            
            # check if the project is valid
            if self.current_project is None: 
                await asyncio.sleep(SLEEPTIME) 
                continue
                        
            try:

                self.project_count += 1

                await self.run_tests()
                
                # remove the project
                await func.removeDir(self.current_project)
                
                self.current_project = None

            except Exception as e:
                logging.error(f"Error processing project: {e}")
            
            finally:
                await asyncio.sleep(SLEEPTIME) 

    """
    run tests from the queue
    """
    async def run_tests(self):
        """
        run tests from the queue
        """
        
        if self.current_project is None:
            logging.warning("No project selected")
            return 
        
        """
        function to display error
        """
        def __error(e):
            logging.error(f"Error running test on {self.current_project} : {e}")
            return 
        
        try:
            
            # execute all tests
            result = await func.pytestCall(self.current_project)
            
            
            if result is None:
                __error("")
                
            self.module_count += func.countModulesFromFile()
                
            passed, failed = result
            
            # update the status
            self.total_passed += passed
            self.total_failed += failed
        
        
        except Exception as e:
            __error(e)
    
    """
    stops node protocol
    """
    def stop(self):

        if self.protocol:
            self.protocol.close()
            logging.info("Protocol closed")

if __name__ == "__main__":

    from initNode import init
    init(8111)