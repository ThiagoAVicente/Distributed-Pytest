# Example for initNode.py
import asyncio
from node import Node
from api import FlaskInterface

import os

# event loop
loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

# create and initialize the node
node = Node(port=int(os.environ.get("PORT_ID", 0)) + 8000)

flask_api = FlaskInterface(node, l=loop)

api_thread = flask_api.start()

# start the node and processing in the event loop
async def start_node():
    await node.start()

    processing_task = asyncio.create_task(node.process_queue())
    listening_task = asyncio.create_task(node.listen())
    await asyncio.gather(processing_task, listening_task)

# run the node in the event loop
try:
    loop.run_until_complete(start_node())
    loop.run_forever()
finally:
    loop.close()
