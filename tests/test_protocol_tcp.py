#!/usr/bin/env python3
"""
test_tcp.py – Test Lynkio in TCP mode (HTTP and WebSocket only).
"""

import asyncio
import json

from lynkio import Lynk, LynkClient

app = Lynk(host="127.0.0.1", port=8766, protocol="TCP", debug=True)

@app.get("/")
async def index(req):
    return "Hello from TCP!"

@app.on("ping")
async def on_ping(client, data):
    await client.send(json.dumps({"event": "pong", "data": data}))

async def main():
    server_task = asyncio.create_task(app._run_forever())
    await asyncio.sleep(1)

    client = LynkClient("127.0.0.1", 8766)

    # HTTP
    status, headers, body = await client.http.get("/")
    print(f"HTTP: {body.decode()}")

    # WebSocket
    await client.ws.connect()
    async def on_pong(data):
        print(f"WebSocket pong: {data}")
    client.ws.on("pong", on_pong)
    await client.ws.emit("ping", "hello")
    await asyncio.sleep(0.5)
    await client.ws.close()

    await app.stop()
    server_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())