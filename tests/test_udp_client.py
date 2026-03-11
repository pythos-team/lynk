import asyncio
import json
from lynkio import LynkClient

async def test_udp():
    client = LynkClient("127.0.0.1", 8765)
    msg = json.dumps({"path": "/udp/echo", "data": "hello from Python"}).encode()
    response = await client.udp.send(msg)
    if response:
        print("Response:", response.decode())
    else:
        print("No response (timeout)")

asyncio.run(test_udp())