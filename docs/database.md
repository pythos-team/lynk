```markdown
# Database Logging with soketDB built-in

Lynkio integrates seamlessly with [soketDB](/soketdb) – a lightweight, file‑based database with optional cloud sync, encryption and sql-like qurel. This integration gives you **automatic logging** of HTTP requests, WebSocket messages, and runtime events, as well as a distributed query API.

## Enabling Database Support

First, ensure `database is enable`:
```

Enable it when creating the Lynk app:

```python
app = Lynk(enable_database=True)
```

## Creating a Database and Log Tables

Use app.create_database() to create a soketDB instance and optionally create the three log tables:

```python
app.create_database(
    name="my_app_logs",
    create_log_table=True,   # creates wss_logs, http_logs, runtime_logs
    auto_sync_log=True       # automatically insert logs
)
```

· http_logs: Stores each HTTP request and response.

· wss_logs: Stores WebSocket messages (both incoming and outgoing) and connection events.

· runtime_logs: Stores server start/stop, scheduled task errors, and manual log entries.

Automatic Logging (when auto_sync_log=True)

Once enabled, Lynk automatically logs:

· Every HTTP request – method, path, status code, client IP, user agent, response time, and request ID.

· Every WebSocket connection and disconnection.
· Every WebSocket message (both JSON and binary), including the event name and payload.

· Server start and stop events.
· Any exception in a scheduled task.

All logs are inserted asynchronously in a thread executor, so they never block the event loop.

## Manual Logging

You can also insert custom log entries using add_log():

```python
await app.add_log('runtime', level='WARNING', message='Custom check passed', source='health_check')
```

The table parameter must be one of 'http', 'wss', or 'runtime'. The keyword arguments must match the table's columns (excluding auto‑generated id and timestamp).

## Querying Logs

Lynkio keeps a global registry of all created databases. You can run any soketDB query on a registered database asynchronously with query_database():

```python
logs = await app.query_database(
    "my_app_logs",
    "SELECT * FROM http_logs ORDER BY id DESC LIMIT 10"
)
```

The query is executed in a thread executor, so it won't block the event loop. The result is whatever db.execute() returns – typically a list of dictionaries.

db.execute() allow multiple methods (CREATE, ALTER, INSERT, UPDATE

```python
db.execute("INSERT INTO secure_users DATA = [{'id': 1, 'name': 'Alice', 'email': 'alice@secure.com', 'password_hash': 'hash123'}]")

db.execute("CREATE TABLE secure_users (id, name, email, password_hash)")
```

## Example: Expose logs via HTTP

```python
@app.get("/logs/http")
async def get_http_logs(req):
    logs = await app.query_database("my_app_logs", "SELECT * FROM http_logs ORDER BY id DESC LIMIT 20")
    return json_response(logs)
```

## Table Schemas

http_logs


```python
Column Type Description
id int Auto‑increment
timestamp str ISO timestamp
method str HTTP method
path str Request path
status_code int HTTP status code
client_ip str Client IP address
user_agent str User‑Agent header
response_time float Time taken to respond (seconds)
request_id str Unique request ID
```

wss_logs

```python
Column Type Description
id int Auto‑increment
timestamp str ISO timestamp
client_id str WebSocket client ID
direction str 'in' (received) or 'out' (sent)
event str Event name (for JSON messages)
data str Payload (JSON string or hex for binary)
size int Payload size in bytes
opcode int WebSocket opcode (1=text,2=binary, etc.)
```

runtime_logs
```python
Column Type Description
id int Auto‑increment
timestamp str ISO timestamp
level str Log level (INFO, ERROR, WARNING, DEBUG)
message str Log message
source str Source component (e.g., 'server', 'scheduler')
```

## Advanced: Using Multiple Databases

You can create multiple databases with different names. Each is stored in the global _databases dictionary and can be queried independently.

```python
app.create_database("users_db")
app.create_database("analytics_db")

# Later
users = await app.query_database("users_db", "SELECT * FROM profiles")
events = await app.query_database("analytics_db", "SELECT * FROM page_views")
```

## Production Considerations

If you enable production mode in database (via database() parameters), all data is encrypted. The encryption key is stored in an environment file; make sure to back it up.
