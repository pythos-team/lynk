```markdown
# Responses

Lynkio handlers can return several types of responses. The framework automatically converts them to proper HTTP responses.
```

## Basic Return Types

### Strings

Returning a string sends it as `text/html`:

```python
@app.get("/")
async def home(req):
    return "<h1>Hello</h1>"
```

## Dictionaries

Returning a dictionary sends it as application/json:

```python
@app.get("/api/status")
async def status(req):
    return {"status": "ok", "uptime": 123}
```

## Bytes

Returning bytes sends them as application/octet-stream:

```python
@app.get("/data")
async def get_data(req):
    return b"raw binary data"
```

## Tuples

Return a tuple (body, content_type) to specify the content type:

```python
@app.get("/custom")
async def custom(req):
    return ("plain text", "text/plain")
```

## Helper Functions

json_response(data, status=200)

Explicitly return a JSON response with a given status code:

```python
from lynkio import json_response

@app.post("/items")
async def create_item(req):
    item = await req.json()
    # ... save item
    return json_response({"id": 123}, status=201)
```

redirect(location, status=302)

Redirect to another URL:

```python
from lynkio import redirect

@app.get("/old")
async def old(req):
    return redirect("/new")
```

## File Responses

send_file(filepath, base_dir=".", content_type=None)

Stream a file to the client. The file is sent in chunks to avoid loading it entirely into memory.

```python
from lynkio import send_file

@app.get("/download")
async def download(req):
    return send_file("report.pdf", base_dir="./files")
```

If content_type is omitted, it is guessed from the file extension.

FileResponse Class

You can also create a FileResponse directly for more control:

```python
from lynkio import FileResponse

@app.get("/video")
async def video(req):
    return FileResponse("movie.mp4", chunk_size=65536)
```

Streaming Responses

StreamingResponse

Stream any async generator with chunked transfer encoding:

```python
from lynkio import StreamingResponse
import asyncio

async def event_stream():
    for i in range(10):
        yield f"data: {i}\n\n"
        await asyncio.sleep(1)

@app.get("/events")
async def sse(req):
    return StreamingResponse(event_stream(), content_type="text/event-stream")
```

## Templates

Lynkio includes a simple template renderer (no external engine). See the Templates section for details.

## CORS Headers

If you have enabled CORS globally with app.enable_cors(), the appropriate headers are automatically added to all responses (including errors).
