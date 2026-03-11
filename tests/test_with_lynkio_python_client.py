#!/usr/bin/env python3
"""
test_with_lynkio_python_client.py – Correctly starts server and client.
Uses the unified LynkClient for WebSocket, HTTP, and UDP.
"""

import asyncio
import json

from lynkio import Lynk, LynkClient, json_response

# ----------------------------------------------------------------------
# Server application
# ----------------------------------------------------------------------
app = Lynk(host="127.0.0.1", port=8765, protocol="AUTO", debug=True)

@app.get("/")
async def index(req):
    return "Hello, HTTP!"

@app.post("/echo")
async def echo(req):
    data = await req.json()
    return json_response(data)

@app.on("ping")
async def on_ping(client, data):
    await client.send(json.dumps({"event": "pong", "data": data}))

@app.udp("/ping")
async def udp_ping(req):
    return json_response({"udp": "pong", "echo": req.body.decode()})

# ----------------------------------------------------------------------
# Test runner
# ----------------------------------------------------------------------
async def main():
    # Start server in background
    server_task = asyncio.create_task(app._run_forever())
    print("Starting server...")
    await asyncio.sleep(1)   # give it time to bind

    # Create unified client
    client = LynkClient("127.0.0.1", 8765)

    # --- HTTP ---
    print("\n=== HTTP ===")
    status, _, body = await client.http.get("/")
    print(f"GET / -> {status} {body.decode()}")

    status, _, body = await client.http.post("/echo", json_data={"test": 123})
    print(f"POST /echo -> {status} {body.decode()}")

    # --- WebSocket ---
    print("\n=== WebSocket ===")
    await client.ws.connect()
    print("WebSocket connected")

    async def on_pong(data):
        print(f"Received pong: {data}")
    client.ws.on("pong", on_pong)

    await client.ws.emit("ping", {"hello": "world"})
    await asyncio.sleep(0.5)   # wait for response

    await client.ws.close()

    # --- UDP ---
    print("\n=== UDP ===")
    msg = json.dumps({"path": "/ping", "data": "hello"}).encode()
    response = await client.udp.send(msg)
    if response:
        print(f"UDP response: {response.decode()}")
    else:
        print("UDP: no response (timeout)")

    # Clean up
    print("\nStopping server...")
    await app.stop()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

if __name__ == "__main__":
    asyncio.run(main())