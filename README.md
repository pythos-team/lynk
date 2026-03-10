```markdown
# Lynk – Real‑time event engine with native HTTP routing


[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Lynk is a lightweight, pure‑Python framework for building real‑time web applications with native HTTP routing and event‑driven architecture. It runs on Python 3.7+ and has **no external dependencies** beyond the standard library (except optional integration with [soketDB](/soketdb) for logging).

---

## ✨ Features

- 🚀 **Real‑time Event Engine** – Handle WebSocket connections, events, and notifications.

- 🌐 **Native HTTP Routing** – Full support for GET, POST, PUT, DELETE, PATCH, OPTIONS.

- 🔌 **Pub/Sub with Rooms** – Publish and subscribe to events across your application.

- ⚡ **Async‑Ready** – Fully compatible with Python’s `asyncio`.

- 🧩 **Middleware Support** – Add custom middleware for WebSocket events and HTTP requests.

- 📦 **Plugin System** – Extend Lynk with reusable modules.

- 🗄️ **Integrated Database Logging**

–Automatically log HTTP, WebSocket, and runtime events to **soketDB** (optional).

- 📊 **Distributed Query API** 

– Query any registered soketDB instance asynchronously.

- 🛠️ **Background Tasks & Scheduler**

– Run periodic or one‑off background coroutines.

- 🔒 **CORS Support** 

– Enable Cross‑Origin Resource Sharing with one line.

- 🐍 **Pure Python** 

– No external dependencies (except soketDB for logging, which is optional).

---

## 📦 Installation

```bash
pip install lynkio
```

If you plan to use the integrated logging feature with some specific backup,:

```bash
pip install lynkio[huggingface]

available backups

[ huggingface, aws, gdrive, dropbox ]
```

---

Quick Start

Create a simple HTTP server:

```python
from lynkio import Lynk

app = Lynk()

@app.get("/")
async def home(req):
    return "Hello, Lynk!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
```

---

Detailed Usage

HTTP Routing

```python
@app.get("/hello")
async def hello(req):
    return {"message": "Hello world"}

@app.post("/data")
async def post_data(req):
    data = await req.json()
    return {"received": data}

@app.route("/users/<user_id>", methods=["GET", "DELETE"])
async def user_handler(req, user_id):
    if req.method == "GET":
        return {"user_id": user_id}
    elif req.method == "DELETE":
        # delete user...
        return {"deleted": user_id}
```

WebSocket Events

```python
@app.on("chat")
async def on_chat(client, data):
    await app.emit_to_room("lobby", "broadcast", data)

@app.on_binary
async def on_binary(client, payload):
    # echo binary back
    await client.send(payload, text=False)

@app.middleware
async def log_middleware(client, event, data):
    print(f"Event {event} from {client.id}")
    # optionally modify data
    return data
```

Integrated Database Logging

Lynk can automatically log HTTP requests, WebSocket messages, and runtime events to a soketDB instance.

Enabling Database Logging

```python
app = Lynk(enable_database=True)

# Create a database instance and the three log tables
app.create_database(
    name="my_app_logs",
    create_log_table=True,   # creates wss_logs, http_logs, runtime_logs
    auto_sync_log=True       # automatically insert logs
)
```

Log Tables

· http_logs: HTTP requests/responses.
· wss_logs: WebSocket messages (both directions) and connection events.
· runtime_logs: Server start/stop, scheduled task errors, and manual entries.

```python
Automatic Logging (when auto_sync_log=True)

· Every HTTP request (method, path, status, client IP, user‑agent, response time, request ID) is logged.
· Every WebSocket connect, disconnect, text message, and binary message is logged.
· Server start, stop, and any error in a scheduled task are logged.
```

Manual Logging

You can insert custom log entries even when auto‑sync is off using add_log:

```python
await app.add_log('runtime', level='WARNING', message='Custom check', source='my_handler')
```

Querying Logs (Distributed Query API)

Lynk keeps a global registry of all created databases. You can run queries on any registered database asynchronously:

```python
# Inside an async handler
logs = await app.query_database(
    "my_app_logs",
    "SELECT * FROM http_logs"
)
return json_response(logs)
```

The query_database method runs the query in a thread executor so it never blocks the event loop.

---

Full Chat Server Example with Logging

Below is a complete real‑time chat server demonstrating HTTP routes, WebSocket events, background tasks, scheduled tasks, static file serving, and integrated logging.

```python
import os
import time
import asyncio
import logging
from lynk import Lynk, json_response, render_template

app = Lynk(
    host="0.0.0.0",
    port=8765,
    rate_limit=20,
    max_body_size=1024*1024,
    debug=True,
    enable_database=True
)

# Create database with log tables
app.create_database(
    name="chat_logs",
    create_log_table=True,
    auto_sync_log=True
)

# Enable CORS
app.enable_cors(allowed_origins=["*"], allow_credentials=True)

# Serve main chat page
@app.get("/")
async def index(req):
    return render_template("index.html", context={"title": "Lynk Chat"})

# Serve static files
app.static("/static", "static")

# REST API group
api = app.group("/api")

@api.get("/rooms")
async def list_rooms(req):
    rooms = [{"name": r, "members": len(m)} for r, m in app._rooms.items()]
    return json_response(rooms)

@api.get("/room/<room_name>/members")
async def room_members(req, room_name):
    members = app.get_room_clients(room_name)
    return json_response(list(members))

# WebSocket events
@app.on("join")
async def on_join(client, data):
    room = data.get("room", "lobby")
    nickname = data.get("nickname", "Anonymous")
    client.session["nickname"] = nickname
    client.session["room"] = room
    app.join_room(client.id, room)
    await app.emit_to_room(room, "user_joined", {"id": client.id, "nickname": nickname}, exclude=client.id)

@app.on("leave")
async def on_leave(client, data):
    room = client.session.get("room")
    if room:
        nickname = client.session.get("nickname", "Anonymous")
        app.leave_room(client.id, room)
        await app.emit_to_room(room, "user_left", {"id": client.id, "nickname": nickname})

@app.on("message")
async def on_message(client, data):
    room = client.session.get("room")
    if room:
        await app.emit_to_room(room, "chat", {
            "from": client.id,
            "nickname": client.session.get("nickname", "Anonymous"),
            "text": data.get("text", "")
        }, exclude=client.id)

@app.on_binary
async def on_binary(client, payload):
    await client.send(payload, text=False)

# Background task
@app.task
async def print_connections():
    while True:
        await asyncio.sleep(10)
        print(f"Active WebSocket connections: {len(app._clients)}")

# Scheduled task every 30 seconds
@app.schedule(30)
async def broadcast_server_time():
    await app.emit_to_room("time", "server_time", {"time": time.time()})

# Plugin example
def health_check_plugin(app):
    @app.get("/health")
    async def health(req):
        return "OK"
app.use(health_check_plugin)

# Endpoint to view recent HTTP logs
@app.get("/logs/http")
async def get_http_logs(req):
    logs = await app.query_database("chat_logs", "SELECT * FROM http_logs ORDER BY id DESC LIMIT 20")
    return json_response(logs)

if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    os.makedirs("static", exist_ok=True)
    logging.basicConfig(level=logging.INFO)
    app.run()
```

---

API Reference (Summary)

```python
Lynk(**options)

· host, port – Server address.
· max_payload_size, max_message_size – WebSocket frame limits.
· max_body_size – Max HTTP body size.
· max_connections – Max concurrent WebSocket clients.
· rate_limit – Messages per second per client.
· enable_database – Enable soketDB integration.
· database_config – Configuration dict for database ie.

  default_config = {
    'primary_storage': 'local, huggingface, aws, google_drive, dropbox',
    'backup_enabled': True,
    'auto_backup_hours': 24,
    'query_cache_enabled': True,
    'auto_sync': True,
    'google_drive_enabled': False,
    'huggingface_enabled': False,
    'aws_s3_enabled': False,
    'dropbox_enabled': False
  }.
```

Database Methods

```python
· create_database(name, create_log_table=False, auto_sync_log=False) – Creates a soketDB instance, optionally creates log tables, and sets auto‑sync flag.

· async add_log(table, **kwargs) – Manually insert a log entry into http, wss, or runtime table.
· async query_database(db_name, query) – Execute a raw soketDB query on any registered database.
```

HTTP Decorators

```python
· @app.get(path), @app.post(path), @app.put(path), @app.delete(path), @app.patch(path), @app.route(path, methods)

· @app.static(prefix, directory) – Serve static files.
```

WebSocket Decorators

```python
· @app.on(event) – Handle JSON messages with an event field.
· @app.on_binary – Handle binary messages.
· @app.on_internal(event) – Handle internal events (connect, disconnect, subscribe, unsubscribe, message).
· @app.middleware – WebSocket middleware.

Actions

· await app.emit(event, data, client_id=None) – Send to one client or broadcast to all if client.id is not specify.

· await app.emit_to_room(room, event, data, exclude=None) – Send to all clients in a room.

· app.join_room(client_id, room), app.leave_room(client_id, room)

· app.get_room_clients(room) -> Set[str]
```

Background Tasks

```python
· @app.task – Runs once when server starts.
· @app.schedule(interval) – Runs periodically (in seconds).
```

Response Helpers

```python
· json_response(data, status=200)
· redirect(location, status=302)
· send_file(filepath, base_dir=".", content_type=None) – Returns a streaming FileResponse.
· render_template(template_name, context=None, template_dir="templates") – Basic template rendering.
```

Request Object

```python
· req.method, req.path, req.headers, req.body, req.client_ip
· await req.json() – Parse JSON body.
· await req.form() – Parse URL‑encoded form.
· req.query_params – Dict of query string parameters.
· req.cookies – Parsed cookies.
```


CLI Usage

Lynk includes a simple CLI to run applications directly:

```bash
python -m lynk myapp:app --host 0.0.0.0 --port 8765 --debug
```

The format is module:app, where app is the Lynk instance variable.

---

CONTRIBUTING

```python
1. Fork the repository.
2. Create a feature branch (git checkout -b feature/amazing-feature).
3. Commit your changes (git commit -m 'Add amazing feature').
4. Push to the branch (git push origin feature/amazing-feature).
5. Open a Pull Request.
```

---

LICENSE
```python
Distributed under the MIT License. See LICENSE for more information.

---

Built by (Alex Austin).
```