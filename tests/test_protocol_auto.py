#!/usr/bin/env python3
"""
test_auto.py – Test Lynkio in AUTO mode (HTTP, WebSocket, UDP concurrently).
Uses the unified LynkClient for all protocols.
"""

import asyncio
import json
import os
import tempfile

from lynkio import Lynk, LynkClient

# ----------------------------------------------------------------------
# Server setup
# ----------------------------------------------------------------------
STATIC_DIR = tempfile.mkdtemp()
with open(os.path.join(STATIC_DIR, "hello.txt"), "w") as f:
    f.write("Hello, static world!")

app = Lynk(host="127.0.0.1", port=8765, protocol="AUTO", debug=True)

@app.get("/")
async def index(req):
    return "Hello, HTTP!"

@app.get("/file")
async def file(req):
    from lynkio import FileResponse
    return FileResponse(os.path.join(STATIC_DIR, "hello.txt"))

@app.on("ping")
async def on_ping(client, data):
    await client.send(json.dumps({"event": "pong", "data": data}))

@app.udp("/udp/ping")
async def udp_ping(req):
    from lynkio import json_response
    return json_response({"udp": "pong", "echo": req.body.decode()})

app.static("/static", STATIC_DIR)

# ----------------------------------------------------------------------
# Test runner
# ----------------------------------------------------------------------
async def main():
    # Start server
    server_task = asyncio.create_task(app._run_forever())
    await asyncio.sleep(1)

    # Create unified client
    client = LynkClient("127.0.0.1", 8765)

    print("\n--- HTTP ---")
    status, headers, body = await client.http.get("/")
    print(f"GET / -> {status} {body.decode()}")
    status, headers, body = await client.http.get("/file")
    print(f"GET /file -> {status} (body length {len(body)})")
    status, headers, body = await client.http.get("/static/hello.txt")
    print(f"GET /static/hello.txt -> {status} {body.decode()}")

    print("\n--- WebSocket ---")
    await client.ws.connect()
    print("WebSocket connected")

    async def on_pong(data):
        print(f"Received pong: {data}")
    client.ws.on("pong", on_pong)

    await client.ws.emit("ping", {"hello": "world"})
    await asyncio.sleep(0.5)

    async def on_bin(data):
        print(f"Binary echo: {data.hex()}")
    client.ws.on_binary(on_bin)
    await client.ws.send_binary(b"\x00\x01\x02\x03")
    await asyncio.sleep(0.5)

    await client.ws.close()

    print("\n--- UDP ---")
    msg = json.dumps({"path": "/udp/ping", "data": {"foo": "bar"}}).encode()
    response = await client.udp.send(msg)
    if response:
        print(f"UDP response: {response.decode()}")
    else:
        print("UDP: no response (timeout)")

    # Clean up
    await app.stop()
    server_task.cancel()
    import shutil
    shutil.rmtree(STATIC_DIR, ignore_errors=True)

if __name__ == "__main__":
    asyncio.run(main())