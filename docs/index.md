## Lynkio documentation

```markdown

Welcome to the Lynkio documentation! Lynkio is a lightweight, pure‑Python framework for building real‑time web applications with native HTTP routing and an event‑driven architecture. It runs on Python 3.7+ and has **no external dependencies** beyond the standard library – though it can optionally integrate with [soketDB](/soketdb) for powerful, automatic logging.

## Why Lynkio?

- **All‑in‑one** – Handles both HTTP and WebSocket in a single, async server.
- **Simple & Familiar** – Decorator‑based routing like Flask, but async and real‑time ready.
- **Batteries Included** – Pub/Sub with rooms, background tasks, scheduled jobs, middleware, static file serving, and template rendering.
- **Observable by Default** – Integrated logging to soketDB gives you HTTP, WebSocket, and runtime logs out‑of‑the‑box (optional but highly recommended).
- **No Dependency Hell** – Runs on pure Python, easy to deploy anywhere.

## Core Features

 
**HTTP Routing** - Full support for GET, POST, PUT, DELETE, PATCH, OPTIONS with path parameters. 
**WebSocket Events** - Handle JSON messages, binary messages, and built‑in events (connect, disconnect).

**Rooms / Pub‑Sub* -  Group clients into rooms and broadcast messages efficiently.    

**Middleware**  - Intercept and modify WebSocket messages or HTTP requests/responses.

**Background Tasks** - Run coroutines at startup or on a schedule (cron‑like).                  


**Static Files**  - Serve files from any directory with automatic MIME type detection.  

**Templates** - Simple variable‑substitution templating (no extra library). 

**CORS** - Enable Cross‑Origin Resource Sharing with one line.

**Database Logging**  - Automatically log every HTTP request, WebSocket message, and runtime event to soketDB(Lynkio built-in database.


**Query API**  - Run raw SQL queries on any registered soketDB instance asynchronously. 

## Quick Start

from lynkio import Lynk

app = Lynk()

@app.get("/")
async def home(req):
    return "Hello, Lynk!"

@app.on("chat")
async def on_chat(client, data):
    await app.emit_to_room("lobby", "broadcast", data)

if __name__ == "__main__":
    app.run()
```
