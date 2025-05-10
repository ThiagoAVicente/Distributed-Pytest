"""
run this file from src/
: script sends a test udp message to the node on localhost/8000
"""

import sys
import os
sys.path.insert(0, os.path.abspath('.'))

from protocol import AsyncProtocol
import asyncio
import logging

IP =  "127.0.0.1"
PORT = 8000
myPort = 9000

async def main():
    protocol = await AsyncProtocol.create((IP, myPort))
    protocol.send({"menssagem":"teste 123"}, (IP, PORT))
    
if __name__ == "__main__":
    
    logging.basicConfig(level=logging.DEBUG)
    
    # create a new event loop
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # run the main function
    loop.run_until_complete(main())