#!/usr/bin/env python3
"""
test_udp.py – Test Lynkio in UDP mode.
No TCP/HTTP/WebSocket are started.
"""

import asyncio
import json

from lynkio import Lynk, LynkClient

app = Lynk(host="127.0.0.1", port=8767, protocol="UDP", debug=True)

@app.udp("/ping")
async def ping(req):
    from lynkio import json_response
    return json_response({"udp": "pong", "echo": req.body.decode()})

async def main():
    server_task = asyncio.create_task(app._run_forever())
    await asyncio.sleep(1)

    client = LynkClient("127.0.0.1", 8767)
    msg = json.dumps({"path": "/ping", "data": "hello"}).encode()
    response = await client.udp.send(msg)
    if response:
        print(f"UDP response: {response.decode()}")
    else:
        print("UDP: no response (timeout)")

    await app.stop()
    server_task.cancel()

if __name__ == "__main__":
    asyncio.run(main())