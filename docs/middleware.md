```markdown
# Middleware

Lynkio supports middleware for both HTTP and WebSocket. Middleware allows you to intercept and modify requests/responses or events before they reach your handlers.

## HTTP Middleware

HTTP middleware is a coroutine that takes a `Request` object and returns either `None` (to continue) or a response (to short‑circuit the chain). Middleware are executed in the order they are added.

### Adding HTTP Middleware

Use `app._http_middleware.append()` or the convenience `app.use()` method (for plugins). Typically you define a function and add it:

```python
async def my_middleware(req):
    print(f"Incoming {req.method} {req.path}")
    # Optionally modify the request
    req.custom_attr = "hello"
    # Return None to continue, or a response to stop
    return None

app._http_middleware.append(my_middleware)
```

## Short‑circuiting

If a middleware returns a response (e.g., a bytes object or a dict that can be turned into a response), that response is sent immediately and no further middleware or handler is called.

Example: Authentication Middleware

```python
async def auth_middleware(req):
    token = req.headers.get("authorization")
    if not token:
        return b"HTTP/1.1 401 Unauthorized\r\nContent-Length: 0\r\n\r\n"
    # Validate token...
    req.user = {"id": 123}
    return None

app._http_middleware.append(auth_middleware)
```

## Built‑in CORS Middleware

Lynkio provides a CORS middleware that you can enable with app.enable_cors():

```python
app.enable_cors(allowed_origins=["https://example.com"], allow_credentials=True)
```

This adds the necessary headers and handles preflight OPTIONS requests automatically.

## WebSocket Middleware

WebSocket middleware is a coroutine that takes (client, event, data) and can optionally modify the data or raise StopProcessing to halt further processing.

Adding WebSocket Middleware

Use the @app.middleware decorator:

```python
@app.middleware
async def log_middleware(client, event, data):
    print(f"Event {event} from {client.id} with data {data}")
    # Optionally modify data
    data["processed"] = True
    return data  # must return the (possibly modified) data
```

Middleware can also raise StopProcessing to prevent the event from reaching the handler:

```python
from lynk import StopProcessing

@app.middleware
async def block_spam(client, event, data):
    if event == "spam":
        raise StopProcessing
    return data
```

## Order of Execution

Middleware runs in the order they are registered, before the event handler. They can modify the data that is passed to subsequent middleware and the final handler.

## Use Cases

· Logging / monitoring
· Rate limiting (though Lynk has built‑in rate limiting)
· Authentication / authorization
· Data validation / transformation
· Blocking certain events

Next

· Learn about configuration options: Configuration