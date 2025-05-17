# Example for initNode.py
import asyncio
from node import Node
import signal
from api import FlaskInterface
import logging

import os

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

shutdown_event = asyncio.Event()

# start the node and processing in the event loop
async def main():
    await node.start()
    
    listening_task = asyncio.create_task(node.listen())
    processing_task = asyncio.create_task(node.process_queue())
    
    await shutdown_event.wait()
    
    await node.stop()
    listening_task.cancel()
    processing_task.cancel()
    
    try:
        await listening_task
    except asyncio.CancelledError:
        pass
        
    try:
        await processing_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":


    # create and initialize the node
    node = Node(port=int(os.environ.get("PORT_ID", 0)) + 8000, 
                new_network=bool(int(os.environ.get("START", 1))))

    ## uncomment to start the flask api
    flask_api = FlaskInterface(node, l=loop)
    api_thread = flask_api.start()
    
    def handle_sigint():
        logging.info("Signint received, stoping node...")
        loop.call_soon_threadsafe(shutdown_event.set)
        
    # register signal handler
    signal.signal(signal.SIGINT, lambda s, f: handle_sigint())
    
    
    # run the node in the event loop
    try:
        loop.run_until_complete(main())
    finally:
        loop.close()
