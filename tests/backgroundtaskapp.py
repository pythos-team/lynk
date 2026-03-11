#!/usr/bin/env python3
"""
backgroundtaskapp.py – Demonstrates Lynkio background tasks and scheduled jobs.
Runs in AUTO mode (TCP+UDP). A background task increments a counter every 0.1s;
a scheduled task runs every 2 seconds. HTTP endpoints expose the counters.
"""

import asyncio
import json
from lynkio import Lynk, json_response

# ----------------------------------------------------------------------
# Application setup
# ----------------------------------------------------------------------
app = Lynk(host="127.0.0.1", port=8765, protocol="AUTO", debug=True)

# Shared state
background_counter = 0
scheduled_counter = 0

# ----------------------------------------------------------------------
# Background task (runs continuously while server is running)
# ----------------------------------------------------------------------
@app.task
async def background_worker():
    global background_counter
    while app._running:
        await asyncio.sleep(0.1)
        background_counter += 1
        # You could also emit WebSocket updates here

# ----------------------------------------------------------------------
# Scheduled task (runs every 2 seconds)
# ----------------------------------------------------------------------
@app.schedule(2.0)
async def scheduled_job():
    global scheduled_counter
    scheduled_counter += 1
    print(f"[scheduled] Tick #{scheduled_counter} at {asyncio.get_event_loop().time():.2f}")

# ----------------------------------------------------------------------
# HTTP endpoints to read counters
# ----------------------------------------------------------------------
@app.get("/counters")
async def get_counters(req):
    return json_response({
        "background": background_counter,
        "scheduled": scheduled_counter
    })

# ----------------------------------------------------------------------
# WebSocket endpoint: clients can listen to live updates
# ----------------------------------------------------------------------
@app.on("subscribe_counters")
async def subscribe_counters(client, data):
    # Send initial value
    await client.send(json.dumps({
        "event": "counters_update",
        "data": {"background": background_counter, "scheduled": scheduled_counter}
    }))
    # In a real app you'd store the client and push updates periodically.
    # For demo, we just send once.

# ----------------------------------------------------------------------
# UDP endpoint: increment counters on demand
# ----------------------------------------------------------------------
@app.udp("/increment")
async def udp_increment(req):
    global background_counter, scheduled_counter
    # Increment both by the value sent in data (or 1)
    body = req.body.decode()
    try:
        data = json.loads(body)
        inc = data.get("inc", 1)
    except:
        inc = 1
    background_counter += inc
    scheduled_counter += inc
    return json_response({
        "background": background_counter,
        "scheduled": scheduled_counter
    })

# ----------------------------------------------------------------------
# Run the server
# ----------------------------------------------------------------------
if __name__ == "__main__":
    print("Starting background task demo on port 8765")
    app.run()