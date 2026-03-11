```markdown
# Routing

Lynkio provides a clean, decorator‑based routing system for both HTTP and WebSocket.

## HTTP Routing

### Basic Routes

Use the method‑specific decorators:

```python
@app.get("/items")
async def get_items(req):
    return {"items": ["apple", "banana"]}

@app.post("/items")
async def create_item(req):
    data = await req.json()
    # ... save item
    return {"status": "created", "item": data}

@app.put("/items/<id>")
async def update_item(req, id):
    data = await req.json()
    return {"updated": id, "data": data}

@app.delete("/items/<id>")
async def delete_item(req, id):
    return {"deleted": id}

@app.patch("/items/<id>")
async def patch_item(req, id):
    data = await req.json()
    return {"patched": id, "data": data}
```

You can also use @app.route() to specify methods manually:

```python
@app.route("/users/<user_id>", methods=["GET", "POST"])
async def user_handler(req, user_id):
    if req.method == "GET":
        return {"user_id": user_id}
    elif req.method == "POST":
        data = await req.json()
        return {"created": user_id, "data": data}
```

## Path Parameters

Parameters are extracted from the path using <parameter> syntax. They are passed as keyword arguments to the handler.

```python
@app.get("/posts/<year>/<month>/<slug>")
async def get_post(req, year, month, slug):
    return {"year": year, "month": month, "slug": slug}
```

Parameters are strings by default; you can convert them in the handler.

## Query Strings

Access query parameters via req.query_params (a dictionary):

```python
@app.get("/search")
async def search(req):
    query = req.query_params.get("q", "")
    page = int(req.query_params.get("page", 1))
    return {"query": query, "page": page}
```

## Route Groups

Group routes under a common prefix with shared middleware:

```python
api = app.group("/api")

@api.get("/status")
async def api_status(req):
    return {"status": "ok"}

@api.post("/data")
async def api_data(req):
    data = await req.json()
    return {"received": data}
```

All routes under /api will now have the prefix, e.g., /api/status and /api/data.

## WebSocket Routing

WebSocket messages are routed based on the event field inside the JSON payload.

## Basic Event Handler

```python
@app.on("greet")
async def on_greet(client, data):
    name = data.get("name", "Anonymous")
    await client.send(json.dumps({"event": "greeting", "data": f"Hello, {name}!"}))
```

The client must send a JSON object like {"event": "greet", "data": {"name": "Alice"}}.

## Binary Messages

Handle binary frames with @app.on_binary:

```python
@app.on_binary
async def on_binary(client, payload):
    # payload is bytes
    await client.send(payload, text=False)  # echo back as binary
```

## Internal Events

Lynkio fires internal events for connection lifecycle. You can listen to them with @app.on_internal:

```python
@app.on_internal("connect")
async def on_connect(client, data):
    print(f"Client {client.id} connected")

@app.on_internal("disconnect")
async def on_disconnect(client, data):
    print(f"Client {client.id} disconnected")

@app.on_internal("subscribe")
async def on_subscribe(client, data):
    print(f"Client {client.id} joined room {data['room']}")

@app.on_internal("unsubscribe")
async def on_unsubscribe(client, data):
    print(f"Client {client.id} left room {data['room']}")

@app.on_internal("message")
async def on_message(client, data):
    print(f"Message from {client.id}: {data}")
```

Wildcard or Catch‑All

If you need to handle all events that don't have a specific handler, you can register a fallback. There's no built‑in wildcard, but you can achieve it by checking inside a single handler:

```python
@app.on("*")
async def catch_all(client, data):
    event = data.get("event")
    payload = data.get("data")
    # handle dynamically
```

(Note: "*" is just a string; you can use any convention.)

Static Files

Serve static files from a directory with app.static():

```python
app.static("/static", "./public")
```

Now files in ./public are served under /static. For example, ./public/style.css is available at /static/style.css.

Directory traversal is automatically prevented.

## Lynkio javascript client

Lynkio automatically serve its client from your running server ie 

```python
from lynkio import Lynk

app = Lynk(serve_client=True)
```

after your server starts running the lynkio javascript client would be accesible from your server at "/lynkio/client.js" automatically.

```python
<script src="/lynkio/client.js></script>
```