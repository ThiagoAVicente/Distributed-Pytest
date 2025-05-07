import asyncio
from typing import Optional
from async_protocol import AsyncProtocol, CDProto
import functions as func

import logging

SLEEPTIME = 0.1

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


def getIp() -> str:
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
        self.testQueue:asyncio.Queue = asyncio.Queue()
        self.current_project:Optional[str] = None
        self.project_status:dict = {}

        # counters
        self.total_passed:int = 0
        self.total_failed:int = 0
        self.project_count:int = 0
        self.this_passed:int = 0
        self.this_failed:int = 0

    async def start(self):
        """
        start the node protocol
        """
        self.protocol = await AsyncProtocol.create(self.addr)
        logging.info(f"Node started at {self.addr}")

    async def send_message(self, message:dict, target_addr:tuple[str,int]):
        """
        send message through the protocol
        """
        if self.protocol:
            self.protocol.send(message, target_addr)
        else:
            raise RuntimeError("Protocol not started. use start() 1st")

    async def listen(self):
        """
        defines the node loop
        """

        # ensure start() was called
        if not self.protocol:
            raise RuntimeError("Protocol not started. use start() 1st")

        logging.info(f"Listening on {self.addr}")
        while True:
            try:
                message, addr = await self.protocol.recv()
                logging.info(f"Received message from {addr} -- {message}")

                # process the message
                await self.process_message(message,addr)

            except asyncio.CancelledError:
                # loop canceled
                break

            except Exception as e:
                logging.error(f"Error receiving message: {e}")
                await asyncio.sleep(SLEEPTIME)

    async def process_message(self, message:dict, addr:tuple[str,int]):
        cmd = message.get("cmd")

        if cmd == "evaluation":
            type = message.get("type")

            if type == "url":
                url= message.get("url")
                token= message.get("token")

                try:
                    if url and token:
                        logging.info(f"Received URL: {url} with token: {token}")

                        project_path:str = await func.downloadFromGithub(token,url)

                        # add project to the queue
                        await self.projectQueue.put(project_path)

                except Exception as e:
                    logging.error(f"Error processing URL: {e}")
                    await asyncio.sleep(SLEEPTIME)

            elif type == "zip":
                pass

        # TODO: add cmds
        else:
            logging.warning(f"Unknown command received: {cmd}")

    async def process_projects(self):
        """
        async function to processes projects
        """
        while True:
            self.current_project = await self.projectQueue.get() # wait for a new project
            if self.current_project is None: 
                await asyncio.sleep(SLEEPTIME) 
                continue

            try:
                # read all tests
                # print(self.current_project)
                tests = await func.getAllTests(self.current_project)
                self.project_count += 1
                logging.info(f"Project {self.project_count} - {self.current_project} - {len(tests)} tests")

                # tests -> queue
                for test in tests:
                    await self.testQueue.put(test)

                await self.run_tests()

                data = {
                    "cmd": "state",
                    "project": self.current_project,
                    "total_passed": self.total_passed,
                    "total_failed": self.total_failed,
                }
                logging.debug(data)

                # reset counters
                self.this_passed = 0
                self.this_failed = 0
                await func.removeDir(self.current_project)

                self.current_project = None

            except Exception as e:
                logging.error(f"Error processing project: {e}")
                await asyncio.sleep(SLEEPTIME)

    async def run_tests(self):
        """
        run tests from the queue
        """
        while not self.testQueue.empty():

            if self.current_project is None:
                logging.warning("No project selected")
                break

            # get test
            test = await self.testQueue.get()
            logging.info(f"Running test: {test}")

            try:
                # run test
                result = await func.unitTest(self.current_project, test)

                if result is None:
                    logging.error(f"Error running test {test}")
                    continue # pytest error

                passed, failed = result
                self.total_passed += passed
                self.total_failed += failed

            except Exception as e:
                logging.error(f"Error running test {test}: {e}")
                await asyncio.sleep(SLEEPTIME)
                
        await asyncio.sleep(SLEEPTIME)

    def stop(self):

        if self.protocol:
            self.protocol.close()
            logging.info("Protocol closed")

if __name__ == "__main__":

    node = Node(8111)

    async def main():
        logging.info("Starting node...")
        await node.start()
        await asyncio.gather(node.listen(), node.process_projects())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Node stopped by user")
        node.stop()
