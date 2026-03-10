# test_lynk_logging.py
import asyncio
import json
import time
from lynkio import Lynk, send_file, render_template, json_response, redirect

# ----------------------------------------------------------------------
# Create Lynk app with database enabled
# ----------------------------------------------------------------------
app = Lynk(
    host="127.0.0.1",
    port=8080,
    debug=True,
    enable_database=True,
    database_config={
        'primary_storage': 'local',
        'backup_enabled': False,
        'auto_sync': True
    }
)

# ----------------------------------------------------------------------
# Create database and log tables with auto-sync ON
# ----------------------------------------------------------------------
app.create_database(
    name="lynk_test_db",
    create_log_table=True,      # creates wss_logs, http_logs, runtime_logs
    auto_sync_log=True          # automatically log all events
)

# ----------------------------------------------------------------------
# HTTP routes
# ----------------------------------------------------------------------
@app.get("/")
async def index(req):
    """Serve a simple HTML page with WebSocket client."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Lynk Test</title>
    </head>
    <body>
        <h1>Lynk Test</h1>
        <div>
            <input id="msg" placeholder="Enter message">
            <button onclick="send()">Send</button>
        </div>
        <div id="log"></div>
        <script>
            const ws = new WebSocket("ws://" + location.host + "/ws");
            ws.onmessage = (e) => {
                const log = document.getElementById('log');
                log.innerHTML += '<p>Received: ' + e.data + '</p>';
            };
            function send() {
                const msg = document.getElementById('msg').value;
                ws.send(JSON.stringify({event: 'chat', data: {text: msg}}));
            }
        </script>
    </body>
    </html>
    """
    return html

@app.get("/hello")
async def hello(req):
    """Simple JSON response."""
    return json_response({"message": "Hello, world!"})

@app.get("/redirect-test")
async def redirect_test(req):
    """Redirect to /hello."""
    return redirect("/hello")

@app.get("/file")
async def file_test(req):
    """Serve a file (create a dummy file first)."""
    # Create a dummy file if it doesn't exist
    if not os.path.exists("test.txt"):
        with open("test.txt", "w") as f:
            f.write("This is a test file.")
    return send_file("test.txt")

@app.post("/data")
async def post_data(req):
    """Receive JSON and echo back."""
    data = await req.json()
    return json_response({"received": data})

# ----------------------------------------------------------------------
# WebSocket events
# ----------------------------------------------------------------------
@app.on("chat")
async def on_chat(client, data):
    """Handle chat messages."""
    print(f"Chat from {client.id}: {data}")
    await client.send(json.dumps({"event": "chat_ack", "data": "Message received"}))
    # Emit to all clients in room "lobby"
    await app.emit_to_room("lobby", "broadcast", f"{client.id} says: {data['text']}")

@app.on_binary
async def on_binary(client, payload):
    """Handle binary messages."""
    print(f"Binary from {client.id}, length {len(payload)}")
    # Echo back as binary
    await client.send(payload, text=False)

@app.middleware
async def ws_middleware(client, event, data):
    """Example middleware that logs event processing time."""
    print(f"Middleware: processing {event}")
    # Optionally modify data
    return data

# ----------------------------------------------------------------------
# Background task (periodic)
# ----------------------------------------------------------------------
@app.task
async def background_worker():
    """Runs once at startup."""
    print("Background worker started")
    await asyncio.sleep(2)
    print("Background worker done")

@app.schedule(10)
async def scheduled_task():
    """Runs every 10 seconds."""
    print("Scheduled task running")
    # Log a runtime event manually (even though auto-sync is on)
    await app.add_log('runtime', level='INFO', message='Scheduled task executed', source='scheduler')

# ----------------------------------------------------------------------
# Route to query logs using the distributed query API
# ----------------------------------------------------------------------
@app.get("/logs/http")
async def get_http_logs(req):
    """Return recent HTTP logs."""
    result = await app.query_database(
        "lynk_test_db",
        "SELECT * FROM http_logs ORDER BY id DESC LIMIT 10"
    )
    return json_response(result)

@app.get("/logs/wss")
async def get_wss_logs(req):
    """Return recent WebSocket logs."""
    result = await app.query_database(
        "lynk_test_db",
        "SELECT * FROM wss_logs ORDER BY id DESC LIMIT 10"
    )
    return json_response(result)

@app.get("/logs/runtime")
async def get_runtime_logs(req):
    """Return recent runtime logs."""
    result = await app.query_database(
        "lynk_test_db",
        "SELECT * FROM runtime_logs ORDER BY id DESC LIMIT 10"
    )
    return json_response(result)

# ----------------------------------------------------------------------
# Additional route to test manual logging (even with auto-sync on)
# ----------------------------------------------------------------------
@app.get("/manual-log")
async def manual_log(req):
    """Insert a manual log entry."""
    await app.add_log('runtime', level='DEBUG', message='Manual log entry', source='manual')
    return "Manual log added"

# ----------------------------------------------------------------------
# Start the server
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import os
    # Ensure the dummy file exists
    if not os.path.exists("test.txt"):
        with open("test.txt", "w") as f:
            f.write("This is a test file.")
    print("Starting Lynk test server...")
    print("Open http://127.0.0.1:8080/ in your browser")
    print("Test endpoints:")
    print("  GET  /hello")
    print("  GET  /redirect-test")
    print("  GET  /file")
    print("  POST /data (with JSON body)")
    print("  GET  /logs/http")
    print("  GET  /logs/wss")
    print("  GET  /logs/runtime")
    print("  GET  /manual-log")
    print("WebSocket endpoint: ws://127.0.0.1:8080/ws")
    app.run()