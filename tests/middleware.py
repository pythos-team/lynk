#!/usr/bin/env python3
"""
middleware.py – Demonstrates Lynkio middleware for HTTP, WebSocket, and UDP.
Runs in AUTO mode (TCP+UDP). HTTP middleware adds a response header;
WebSocket middleware modifies incoming messages; UDP middleware (same as HTTP)
adds a timestamp to the request.
"""

import asyncio
import json
import time
from lynkio import Lynk, json_response, Request

# ----------------------------------------------------------------------
# Application setup
# ----------------------------------------------------------------------
app = Lynk(host="127.0.0.1", port=8765, protocol="AUTO", debug=True)

# ----------------------------------------------------------------------
# HTTP middleware (also applies to UDP because UDP uses Request objects)
# ----------------------------------------------------------------------
@app._http_middleware.append
async def http_middleware(req: Request):
    """Add a timestamp to the request and log the method."""
    req._mw_timestamp = time.time()
    print(f"[HTTP middleware] {req.method} {req.path} from {req.client_ip}")
    # If we wanted to modify the response, we would return a special object.
    # Here we just pass through.
    return None  # None means continue processing

# ----------------------------------------------------------------------
# WebSocket middleware
# ----------------------------------------------------------------------
@app.middleware
async def ws_middleware(client, event, data):
    """Log and optionally modify WebSocket messages."""
    print(f"[WebSocket middleware] event={event}, client={client.id}")
    # Add a "middleware" field to the data
    data["middleware"] = "processed"
    return data  # return the (possibly modified) data

# ----------------------------------------------------------------------
# Endpoints to demonstrate middleware effects
# ----------------------------------------------------------------------
@app.get("/")
async def index(req):
    # The request now has req._mw_timestamp set by middleware
    return json_response({
        "message": "Hello, world!",
        "timestamp": getattr(req, "_mw_timestamp", None)
    })

@app.on("ping")
async def on_ping(client, data):
    # data should contain "middleware": "processed"
    await client.send(json.dumps({"event": "pong", "data": data}))

@app.udp("/udp/echo")
async def udp_echo(req):
    # UDP requests also go through HTTP middleware, so req._mw_timestamp is set
    return json_response({
        "echo": req.body.decode(),
        "timestamp": getattr(req, "_mw_timestamp", None)
    })

# ----------------------------------------------------------------------
# Run the server
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("Starting middleware demo on port 8765")
    app.run()