```markdown
# File Handling

Lynk provides utilities for serving static files and streaming file downloads.

## Serving Static Files

The simplest way to serve a directory of static assets is `app.static()`:

```python
app.static("/static", "./public")
```

Now any file inside ./public is accessible under /static. For example, ./public/css/style.css → /static/css/style.css.

Directory traversal is automatically prevented – requests containing .. are rejected with a 403.

## Streaming File Downloads

Use send_file() to stream a file to the client. This is efficient because the file is read in chunks and never loaded entirely into memory.

```python
from lynkio import send_file

@app.get("/download/<filename>")
async def download(req, filename):
    # Security: ensure filename is safe
    if ".." in filename or filename.startswith("/"):
        abort(403)
    return send_file(filename, base_dir="./downloads")
```

If content_type is not provided, it is guessed from the file extension using mimetypes.

## Custom Chunk Size

You can create a FileResponse directly to control the chunk size:

```python
from lynkio import FileResponse

@app.get("/large-file")
async def large_file(req):
    return FileResponse("bigfile.bin", chunk_size=1024*1024)  # 1 MB chunks
```

## Streaming Arbitrary Data

For dynamic content (e.g., server‑sent events, live video), use StreamingResponse with an async generator:

```python
from lynkio import StreamingResponse
import asyncio
import time

async def clock_stream():
    while True:
        yield f"data: {time.time()}\n\n"
        await asyncio.sleep(1)

@app.get("/clock")
async def clock(req):
    return StreamingResponse(clock_stream(), content_type="text/event-stream")
```

The generator should yield bytes or str. If it yields str, it is encoded to UTF‑8.

## Upload Handling

Lynkio does not handle multipart file uploads natively, but you can access the raw body and parse it yourself. For simple use cases, you can accept the file as a binary body:

```python
@app.post("/upload")
async def upload(req):
    file_data = req.body
    # save to disk
    with open("uploaded_file", "wb") as f:
        f.write(file_data)
    return {"size": len(file_data)}
```

For more complex uploads (multipart/form-data), you would need to parse the boundary – you can use the standard library's email.message or a third‑party library.

Next

· Learn about middleware: Middleware