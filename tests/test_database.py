#!/usr/bin/env python3
"""
test_database_api.py – Demonstrates correct usage of Lynkio's database API.
- Creates a database with log tables and auto‑sync enabled.
- Exercises HTTP, WebSocket, and UDP endpoints.
- Queries the database using app.query_database() to verify logs.
- Uses only the lynkio package and Python standard library.
"""

import asyncio
import json
import os
import tempfile

from lynkio import (
    Lynk,
    LynkClient,
    json_response,
    FileResponse,
)

# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
HOST = "127.0.0.1"
PORT = 8888
STATIC_DIR = tempfile.mkdtemp()
DB_NAME = "lynkio_test_db"

# Create a sample static file (for HTTP file response)
with open(os.path.join(STATIC_DIR, "hello.txt"), "w") as f:
    f.write("Hello, static world!")

# ----------------------------------------------------------------------
# Lynk application with database enabled
# ----------------------------------------------------------------------
app = Lynk(
    host=HOST,
    port=PORT,
    protocol="AUTO",          # runs HTTP, WebSocket, and UDP
    debug=True,
    enable_database=True,     # required to use create_database
)

# Create the database and enable auto‑logging
db = app.create_database(
    DB_NAME,
    create_log_table=True,    # creates http_logs, wss_logs, runtime_logs
    auto_sync_log=True,       # automatically logs all requests/responses
)

# ----------------------------------------------------------------------
# Define endpoints to generate log entries
# ----------------------------------------------------------------------
@app.get("/")
async def index(req):
    return "Hello, HTTP!"

@app.post("/echo")
async def echo(req):
    data = await req.json()
    return json_response(data)

@app.get("/file")
async def file(req):
    return FileResponse(os.path.join(STATIC_DIR, "hello.txt"))

# WebSocket event
@app.on("ping")
async def on_ping(client, data):
    await client.send(json.dumps({"event": "pong", "data": data}))

# UDP endpoint
@app.udp("/udp/ping")
async def udp_ping(req):
    return json_response({"udp": "pong", "echo": req.body.decode()})

# Static files (also generates logs)
app.static("/static", STATIC_DIR)

# ----------------------------------------------------------------------
# Helper to query a table using the distributed API
# ----------------------------------------------------------------------
async def query_table(table: str) -> list:
    """Return all rows from the given table in DB_NAME."""
    # app.query_database runs the query in a thread executor (non‑blocking)
    return await app.query_database(DB_NAME, f"SELECT * FROM {table}")

# ----------------------------------------------------------------------
# Test runner
# ----------------------------------------------------------------------
async def main():
    # Start server in background
    server_task = asyncio.create_task(app._run_forever())
    await asyncio.sleep(1)   # give it time to start

    # Create unified client
    client = LynkClient(HOST, PORT)

    print("=== Generating activity (logs will be written to database) ===")

    # --- HTTP ---
    print("GET /")
    await client.http.get("/")
    print("POST /echo")
    await client.http.post("/echo", json={"foo": "bar"})
    print("GET /file")
    await client.http.get("/file")
    print("GET /static/hello.txt")
    await client.http.get("/static/hello.txt")

    # --- WebSocket ---
    print("WebSocket ping")
    await client.ws.connect()
    await client.ws.emit("ping", {"hello": "database"})
    await asyncio.sleep(0.5)
    await client.ws.close()

    # --- UDP ---
    print("UDP /udp/ping")
    msg = json.dumps({"path": "/udp/ping", "data": "udp-test"}).encode()
    await client.udp.send(msg)

    # Allow time for async logs to be written
    await asyncio.sleep(2)

    # ------------------------------------------------------------------
    # Query the database using the distributed API
    # ------------------------------------------------------------------
    print("\n=== Querying database ===")

    # Query http_logs
    http_logs = await query_table("http_logs")
    print(f"\nhttp_logs ({len(http_logs)} entries):")
    for row in http_logs[-3:]:   # show last 3
        print(f"  {row}")

    # Query wss_logs
    wss_logs = await query_table("wss_logs")
    print(f"\nwss_logs ({len(wss_logs)} entries):")
    for row in wss_logs[-3:]:
        print(f"  {row}")

    # Query runtime_logs
    runtime_logs = await query_table("runtime_logs")
    print(f"\nruntime_logs ({len(runtime_logs)} entries):")
    for row in runtime_logs[-3:]:
        print(f"  {row}")

    # Basic sanity check
    assert len(http_logs) >= 4, "Expected at least 4 HTTP log entries"
    assert len(wss_logs) >= 1, "Expected at least 1 WebSocket log entry"
    assert len(runtime_logs) >= 1, "Expected at least 1 runtime log entry (server start)"

    # ------------------------------------------------------------------
    # Clean up
    # ------------------------------------------------------------------
    print("\nStopping server...")
    await app.stop()
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    import shutil
    shutil.rmtree(STATIC_DIR, ignore_errors=True)
    print("Test completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())