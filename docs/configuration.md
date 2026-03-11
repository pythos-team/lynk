```markdown
# Configuration

When creating a Lynkio instance, you can pass various options to control its behavior. All options have sensible defaults.

## Constructor Parameters

```python
app = Lynk(
    host="0.0.0.0",
    port=8765,
    max_payload_size=256 * 1024,      # 256 KiB per WebSocket frame
    max_message_size=1024 * 1024,     # 1 MiB total fragmented message
    max_body_size=1024 * 1024,        # 1 MiB HTTP body
    room_batch_size=100,               # clients per batch in room broadcasts
    max_connections=None,               # max concurrent WebSocket clients (None = unlimited)
    allowed_origins=None,               # list of allowed origins for WebSocket
    rate_limit=None,                     # messages per second per WebSocket client
    enable_keep_alive=False,             # whether to support HTTP keep‑alive
    debug=False,                          # enable debug logging
    enable_database=False,                # enable soketDB integration
    database_config=None                   # configuration dict for soketDB
)
```

## Parameter Details

```text
Parameter Default Description
host "0.0.0.0" Host to bind to.
port 8765 Port to listen on.
max_payload_size 262144 (256K) Maximum size of a single WebSocket frame.
max_message_size 1048576 (1M) Maximum size of a complete WebSocket message (after reassembly).
max_body_size 1048576 (1M) Maximum size of an HTTP request body.
room_batch_size 100 Number of clients to include in each batch when broadcasting to a room (prevents event loop blocking).
max_connections None Maximum number of concurrent WebSocket clients. If exceeded, new connections receive 503.
allowed_origins None List of allowed origins for WebSocket connections (e.g., ["https://example.com"]). If None, all origins are allowed.
rate_limit None Maximum number of WebSocket messages per second per client.
enable_keep_alive False If True, the server will keep HTTP connections alive (requires clients to send Connection: keep-alive).
debug False If True, sets logging level to DEBUG and prints more verbose output.
enable_database False Enables integration with soketDB for logging. Requires soketdb package.
database_config None Configuration dictionary passed to soketdb.database(). See soketDB docs.
```

## CORS Configuration

CORS is not enabled by default. Use `app.enable_cors()` to configure it:

```python
app.enable_cors(allowed_origins=["*"], allow_credentials=False)
```

· allowed_origins: List of origins allowed to access the server. Use ["*"] to allow any origin.
· allow_credentials: If True, the Access-Control-Allow-Credentials header is set to true.

This adds a middleware that handles preflight OPTIONS requests and adds the appropriate headers to all responses.

## Database Configuration Example

```python
app = Lynk(enable_database=True, database_config={
    'primary_storage': 'local',
    'backup_enabled': True,
    'auto_backup_hours': 24,
    'auto_sync': True,
    'google_drive_enabled': False,
    'huggingface_enabled': False,
    'aws_s3_enabled': False,
    'dropbox_enabled': False
})
```

## Environment Variables

Lynkio itself does not read environment variables, but soketDB can. If you enable database logging, you can use env() from soketDB to manage sensitive configuration.

Next

· Learn about deployment in production: Deployment