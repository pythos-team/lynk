from lynkio import Lynk, json_response

app = Lynk(host="0.0.0.0", port=8765, protocol="AUTO", debug=True)

# WebSocket handler for "__udp" – forwards messages to UDP router
@app.on("__udp")
async def handle_udp_via_ws(client, data):
    path = data.get("path")
    payload = data.get("data", {})
    # Reconstruct a UDP‑like request and feed it into the UDP handler
    # We create a fake UDP address (client's IP is not directly available)
    fake_addr = (client.writer.get_extra_info('peername')[0], 0)
    # Build a Request object (simulate UDP datagram)
    req = Request(
        method="UDP",
        path=path,
        headers={},
        body=json.dumps(payload).encode(),
        client_ip=fake_addr[0]
    )
    # Call the internal UDP handler
    await app._handle_udp_datagram(req.body, fake_addr, fake_addr[0], fake_addr[1])

# UDP route
@app.udp("/ping")
async def udp_ping(req):
    # This will be called when a UDP datagram arrives (or via the WebSocket bridge)
    return json_response({"udp": "pong", "echo": req.body.decode()})

# (Optional) If you want to send the UDP response back to the client via WebSocket,
# you could emit a WebSocket event from the UDP handler, but that's application‑specific.