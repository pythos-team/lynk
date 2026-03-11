#!/usr/bin/env python3
"""
test_http.py – Test Lynkio HTTP endpoints in TCP mode.
No WebSocket used.
"""

import asyncio
import json

from lynkio import Lynk, LynkClient, json_response

app = Lynk(host="127.0.0.1", port=8768, protocol="TCP", debug=True)

@app.get("/")
async def index(req):
    return "Hello, HTTP!"

@app.post("/echo")
async def echo(req):
    data = await req.json()
    return json_response(data)

async def main():
    server_task = asyncio.create_task(app._run_forever())
    await asyncio.sleep(1)

    client = LynkClient("127.0.0.1", 8768)

    # GET
    status, headers, body = await client.http.get("/")
    print(f"GET / -> {status} {body.decode()}")

    # POST JSON
    status, headers, body = await client.http.post("/echo", json_data={"test": 123})
    print(f"POST /echo -> {status} {body.decode()}")

    await app.stop()
    server_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())