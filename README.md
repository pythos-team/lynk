## Lynkio – Pure‑Python Real‑Time Event Engine

Lynkio is a lightweight, high‑performance framework for building real‑time web applications with native HTTP routing, WebSockets (RFC6455), UDP datagram handling, and an AUTO mode that serves TCP (HTTP/WS) and UDP concurrently on the same port.
It runs on Python 3.7+ and has no external dependencies – only the standard library. Optional integration with soketDB provides automatic logging and distributed database queries.

## [Visit Lynkio Website](https://pythos-team.github.io/lynkio-doc/)
---

## ✨ Features

```text
Category Capabilities
HTTP Path parameters (/user/<id>), method shortcuts (GET, POST, PUT, DELETE, PATCH), route groups, middleware, file streaming, redirects, JSON responses, template rendering, static serving
WebSocket Event‑driven messaging, fragmentation, binary frames, named binary events, automatic heartbeat (ping/pong), per‑client session storage
UDP + AUTO UDP datagram routing (JSON messages), same port for HTTP/WS + UDP, token‑based rate limiting
Rooms & Pub/Sub Join/leave rooms, batch emission, emit_to_room, get_room_clients
Background @app.task (startup coroutines), @app.schedule(interval) (cron‑like periodic tasks)
Database Built‑in soketDB integration: automatic logging of HTTP, WebSocket, runtime events. Distributed query API across any registered database
Middleware WebSocket and HTTP middleware chains; group‑level middleware
CORS One‑line CORS enable with allowed origins & credentials
Plugin system Extend Lynkio via app.use(plugin)
Client libraries Built‑in JavaScript client (served at /lynkio/client.js) + full async Python client
Pure Python Zero extra dependencies – only asyncio and the standard library
```
---

## 📦 Installation

```bash
pip install lynkio==1.2.7
```

If you need cloud backups for soketDB (Hugging Face, AWS S3, Google Drive, Dropbox), install with extras:

```bash
pip install lynkio[huggingface]   # or [aws], [gdrive], [dropbox], or [all]
```

---

## 🚀 Quick Start (HTTP + WebSocket + UDP)

```python
from lynkio import Lynk

app = Lynk(host="0.0.0.0", port=8765, protocol="AUTO", debug=True)

@app.get("/")
async def home(req):
    return "<h1>Hello Lynkio</h1>", "text/html"

@app.on("ping")
async def pong(client, data):
    await client.send("pong")

@app.udp("/sensor")
async def sensor(req):
    data = await req.json()
    print(f"UDP datagram: {data}")
    return {"status": "ok"}

if __name__ == "__main__":
    app.run()
```

Run with: python server.py
Now you have a single server accepting HTTP, WebSocket connections, and UDP datagrams on port 8765.

---

## 📡 HTTP Routing – Deep Dive

Path parameters and methods

```python
@app.get("/users/<user_id>")
async def get_user(req, user_id):
    return {"user_id": user_id}

@app.post("/items")
async def create_item(req):
    data = await req.json()
    return json_response({"id": 123, ...}, status=201)

@app.route("/posts/<post_id>", methods=["PUT", "DELETE"])
async def modify_post(req, post_id):
    if req.method == "PUT":
        ...
    elif req.method == "DELETE":
        ...
```

## Response helpers

```python
from lynkio import json_response, redirect, send_file, abort

@app.get("/old")
async def old_route(req):
    return redirect("/new", status=302)

@app.get("/report")
async def report(req):
    return send_file("docs/summary.pdf", as_attachment=True, cache_control="max-age=3600")

@app.get("/secret")
async def secret(req):
    if not req.headers.get("Authorization"):
        abort(403, "Forbidden")
    return "ok"
```

## Route groups & middleware

```python
api = app.group("/api/v1")

@api.get("/status")
async def api_status(req):
    return {"status": "running"}
```

## Static files & templates

```python
app.static("/static", "public")          # serve ./public

from lynkio import render_template
@app.get("/welcome")
async def welcome(req):
    return render_template("index.html", {"name": "Lynkio"}, template_dir="templates")
```

---

## 🔌 WebSocket Events & Real‑time Messaging

Event handlers

```python
@app.on("echo")
async def echo(client, data):
    await client.send(data)                     # send JSON back

@app.on("set_name")
async def set_name(client, data):
    client.session["name"] = data["name"]       # per‑client session
```

## Rooms (Pub/Sub)

```python
@app.on("join")
async def join_room(client, data):
    room = data["room"]
    app.join_room(client.id, room)
    await app.emit_to_room(room, "system", f"{client.id} joined")

@app.on("message")
async def chat_msg(client, data):
    room = client.session.get("room")
    if room:
        await app.emit_to_room(room, "chat", {
            "from": client.id,
            "text": data["text"]
        })
```

## Binary events (live streaming)

```python
# Send a named binary event to a client
await app.send_binary_event(client_id, "video_frame", frame_bytes)

# Receive named binary events
@app.on_binary_event("audio")
async def handle_audio(client, payload: bytes):
    print(f"Received audio chunk: {len(payload)} bytes")
    await app.send_binary_event(client.id, "audio_ack", b"OK")
```

## WebSocket middleware

```python
@app.middleware
async def auth_mw(client, event, data):
    if event == "admin" and not client.session.get("auth"):
        raise StopProcessing        # reject event
    return data                     # optionally mutate data
```

---

## 📡 UDP & AUTO Mode

Lynkio can run a UDP datagram server on the same port as HTTP/WebSocket (AUTO mode) or standalone.

Registering UDP routes

```python
@app.udp("/log")
async def udp_log(req):
    payload = await req.json()
    # payload = {"path": "/log", "data": {...}, "client_id": optional}
    print(payload)
    return {"status": "logged"}
```

Sending UDP datagrams from Python

```python
import socket, json
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
msg = json.dumps({"path": "/log", "data": {"temp": 22.5}, "client_id": "sensor1"})
sock.sendto(msg.encode(), ("127.0.0.1", 8765))
```

Rate limiting for UDP is based on client_id (or IP:port if not provided). Set rate_limit in Lynk().

---

## 🧠 Background Tasks & Scheduler

One‑time background task (starts with server)

```python
@app.task
async def cache_warmer():
    while app._running:
        await asyncio.sleep(60)
        # refresh cache
```

## Periodic scheduled tasks

```python
@app.schedule(interval=10.0)   # seconds
async def broadcast_time():
    await app.emit("server_time", {"now": time.time()})
```

Scheduled tasks run in the background and are automatically cancelled during graceful shutdown.

---

## 🗄️ Database & Automatic Logging (soketDB)

Lynkio ships with soketDB – a file‑based database with backup, caching, and async support. Enable it to automatically log HTTP requests, WebSocket messages, and runtime events.

Enable database logging

```python
app = Lynk(enable_database=True)
db = app.create_database(
    name="myapp_logs",
    create_log_table=True,   # creates http_logs, wss_logs, runtime_logs
    auto_sync_log=True       # auto‑insert every request/event
)
```

## Log tables

· http_logs – method, path, status, client_ip, user_agent, response_time, request_id
· wss_logs – direction, event, data size, opcode, client_id
· runtime_logs – level, message, source

## Manual logging

```python
await app.add_log("runtime", level="INFO", message="Custom event", source="auth")
```

## Distributed queries across any registered database

```python
# Inside any async handler
rows = await app.query_database(
    "myapp_logs",
    "SELECT method, path FROM http_logs WHERE status_code = $1",
    (200,)
)
for row in rows:
    print(row)
```

---

## 🔧 Middleware, CORS & Plugin System

HTTP middleware

```python
async def my_http_middleware(req):
    print(f"{req.method} {req.path}")
    # return None to continue, or return bytes to short‑circuit
    return None

app._http_middleware.append(my_http_middleware)
```

## CORS (one line)

```python
app.enable_cors(allowed_origins=["https://example.com"], allow_credentials=True)
```

## Plugin system

```python
def metrics_plugin(app):
    @app.get("/metrics")
    async def metrics(req):
        return {"active_clients": len(app._clients)}

app.use(metrics_plugin)
```

---

## 🌐 Clients

Built‑in JavaScript client

Set serve_client=True in Lynk() – the client is served at /lynkio/client.js:

```html
<script src="/lynkio/client.js"></script>
<script>
  const client = new LynkClient("ws://localhost:8765");
  client.on("chat", msg => console.log(msg));
  client.connect().then(() => {
    client.joinRoom("general");
    client.emit("chat", { room: "general", text: "hi" });
    client.sendBinaryEvent("image", new Uint8Array([1,2,3]));
  });
</script>
```

## Full Python client

```python
from lynkio import LynkClient

async def demo():
    client = LynkClient("localhost", 8765)
    await client.ws.connect()
    client.on("greeting", lambda d: print(d))
    await client.ws.emit("ping", "hello")

    # HTTP client
    status, headers, body = await client.http.get("/api/status")
    print(status, body)

    # UDP client
    resp = await client.udp.send(b'{"path":"/ping"}')
    print(resp)

asyncio.run(demo())
```

---

## 🧩 Complete Chat Server Example

```python
import asyncio, time, os
from lynkio import Lynk, render_template

app = Lynk(host="0.0.0.0", port=8765, protocol="AUTO", debug=True,
           enable_database=True)
app.create_database("chat_logs", create_log_table=True, auto_sync_log=True)
app.enable_cors()

@app.get("/")
async def index(req):
    return render_template("chat.html", {"title": "Lynk Chat"})

app.static("/static", "static")

@app.on("join")
async def join(client, data):
    room = data.get("room", "lobby")
    name = data.get("name", "Anonymous")
    client.session["name"] = name
    client.session["room"] = room
    app.join_room(client.id, room)
    await app.emit_to_room(room, "system", f"{name} joined")

@app.on("message")
async def message(client, data):
    room = client.session.get("room")
    if room:
        await app.emit_to_room(room, "chat", {
            "from": client.session.get("name"),
            "text": data["text"]
        })

@app.task
async def stats_printer():
    while app._running:
        await asyncio.sleep(10)
        print(f"Clients: {len(app._clients)}")

if __name__ == "__main__":
    os.makedirs("templates", exist_ok=True)
    app.run()
```

---

## 📖 API Reference (Summary)

```text
## Lynk(**options)

Parameter Default Description
host "0.0.0.0" Bind address
port 8765 Port
protocol "TCP" "TCP", "UDP", or "AUTO"
max_payload_size 256*1024 Max WebSocket frame / UDP datagram
max_message_size 1024*1024 Max fragmented WebSocket message
max_body_size 1024*1024 Max HTTP body
rate_limit None Messages/sec per client/UDP token
enable_database False Enable soketDB logging
serve_client False Serve built‑in JS client

## Core methods

· HTTP: @app.get, .post, .put, .delete, .patch, .route, .static, .group
· WebSocket: @app.on(event), @app.on_binary, @app.on_binary_event(name), @app.middleware
· UDP: @app.udp(path)
· Rooms: join_room(), leave_room(), emit_to_room(), get_room_clients()
· Broadcast: emit(event, data, client_id=None)
· Background: @app.task, @app.schedule(interval)
· Database: create_database(), query_database(), add_log()
· Misc: enable_cors(), use(plugin), fetch(url, ...)

## Request object

· req.method, req.path, req.headers, req.body, req.client_ip
· await req.json(), await req.form(), req.query_params, req.cookies

## Response helpers
· json_response(data, status), redirect(location, status), abort(code, message)
· send_file(filepath, as_attachment=False, cache_control=None, ...)
· render_template(template_name, context, template_dir)
---
```

## 🖥️ CLI Usage

```bash
python -m lynkio myapp:app --host 0.0.0.0 --port 8765 --protocol AUTO --debug
```

The format is module:app where app is your Lynk instance.

---

## 🤝 Contributing

```text
1. Fork the repository
2. Create a feature branch (git checkout -b feature/amazing)
3. Commit your changes
4. Push to the branch
5. Open a Pull Request

---
```

## Lynkio Version

```python
pip install lynkio==1.2.7

Avaible Versions

 v1.1.4
 
 v1.1.5
 
 v1.1.6
 
 v1.1.7
 
 v1.1.8
 
 v1.1.9
 
 v1.2.0
 
 v1.2.1
 
 v1.2.3
 
 v1.2.4
 
 v1.2.5
 
 v1.2.6
 
 v1.2.7 (new)
```

## 📄 License

MIT License – see LICENSE for details.

---

## 👤 Built by Alex Austin

Lynkio is a modern, dependency‑free real‑time framework for Python developers who value simplicity and performance.