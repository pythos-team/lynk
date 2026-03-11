```markdown
# Request Object

Every HTTP handler receives a `Request` object as its first argument. It contains all information about the incoming request.

## Basic Attributes

## `method` 
Type - `str`
description - HTTP method (uppercase)

## `path`
Type - `str`
description - Full request path (including query string)
## `headers`
Type - `Dict[str, str]`
description - Headers (lowercase keys)  

## `body`
Type - `bytes`
description - Raw request body                  

## `client_ip`
Type - `str`
Client IP address (from peername)

## `start_time` 
Type - `float`
description - Timestamp when request processing started

## `request_id` 
Type - `str`
description = Unique ID generated for each request

```

## Parsing the Body

### JSON

```python
data = await req.json()
```

This parses the body as JSON and returns a Python object. It caches the result, so subsequent calls are cheap.

Form Data (URL‑encoded)

```python
form = await req.form()
```

Returns a dictionary of key‑value pairs.

Raw Body

If you need the raw bytes, use req.body.

Query Parameters

Access the parsed query string via req.query_params (a dictionary):

```python
search = req.query_params.get("q", "")
page = int(req.query_params.get("page", 1))
```

## Cookies

Parse the Cookie header with req.cookies:

```python
session_id = req.cookies.get("session")
```

## Custom Attributes

You can attach arbitrary data to the request object; it will persist throughout the request lifecycle.

```python
req.user = await authenticate(req)
```

Later middleware or the handler can access req.user.

## WebSocket Client Object

In WebSocket handlers, the first argument is a Connection object representing the client.

## Connection Attributes

Attribute Type Description
id str Unique client ID
session dict Session dictionary (persists for the connection)
rooms Set[str] Set of rooms this client belongs to
closed bool True if connection is closed

## Connection Methods

· await client.send(payload, text=True) – Send a string (text=True) or bytes (text=False) message.
· await client.ping() – Send a ping frame.
· await client.close(code=1000, reason="") – Close the connection.

## Session Data

You can store per‑client data in client.session:

```python
@app.on("login")
async def on_login(client, data):
    client.session["user"] = data["username"]
```

Session data persists until the client disconnects.
