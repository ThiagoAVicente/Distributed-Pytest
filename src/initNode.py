import asyncio
from async_node import Node


def init(port:int):

    node = Node(port)

    async def main():
        await node.start()
        await asyncio.gather(node.listen(), node.process_projects())

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        node.stop()