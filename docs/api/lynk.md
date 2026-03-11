```markdown
# API Reference: Lynk Class

The `Lynk` class is the main application class. It manages the server, routes, WebSocket clients, rooms, and database integration.

## Constructor

```python
Lynk(
    host: str = "0.0.0.0",
    port: int = 8765,
    max_payload_size: int = 256 * 1024,
    max_message_size: int = 1024 * 1024,
    max_body_size: int = 1024 * 1024,
    room_batch_size: int = 100,
    max_connections: Optional[int] = None,
    allowed_origins: Optional[List[str]] = None,
    rate_limit: Optional[int] = None,
    enable_keep_alive: bool = False,
    debug: bool = False,
    enable_database: bool = False,
    database_config: Optional[dict] = None,
)
```

See Configuration for details.

## Methods

Database Integration

```python
create_database(name: str, create_log_table: bool = False, auto_sync_log: bool = False) -> database
```

Creates a soketDB instance with the given name. If create_log_table is True, creates the three log tables (http_logs, wss_logs, runtime_logs). If auto_sync_log is True, automatic logging is enabled.

The created database is stored in the global registry _databases.

```python
async query_database(db_name: str, query: str) -> Any
```

Executes a raw soketDB query on a named database. The query runs in a thread executor and returns the result.

```python

async add_log(table: str, **kwargs)

```

Manually inserts a log entry into the specified table ('http', 'wss', or 'runtime'). Keyword arguments must match the table's columns.

## HTTP Routing
```python

@app.route(path: str, methods: Optional[List[str]] = None) -> Callable

Decorator to register an HTTP route. methods is a list of allowed HTTP methods (default ["GET"]).

@app.get(path: str), @app.post(path: str), @app.put(path: str), @app.delete(path: str), @app.patch(path: str)

Shortcuts for common methods.

@app.static(prefix: str, directory: str)

Serves static files from directory under URL prefix.

```

## WebSocket

```python

@app.on(event: str) -> Callable

Registers a handler for WebSocket JSON messages with the given event name.

@app.on_binary

Registers a handler for binary WebSocket messages.

@app.on_internal(event: str) -> Callable

Registers a handler for internal events ("connect", "disconnect", "subscribe", "unsubscribe", "message").

@app.middleware

Decorator to register WebSocket middleware.

Room and Broadcast

async def emit(event: str, data: Any, client_id: Optional[str] = None)

Sends an event to a specific client (if client_id given) or to all connected clients (if client_id is None).

async def emit_to_all_except(event: str, data: Any, exclude_ids: List[str])

Broadcasts to all clients except those listed.

async def emit_to_room(room: str, event: str, data: Any, exclude: Optional[str] = None)

Sends an event to all clients in a room, optionally excluding one client.

def join_room(client_id: str, room: str)

Adds a client to a room.

def leave_room(client_id: str, room: str)

Removes a client from a room.

def get_room_clients(room: str) -> Set[str]

Returns a copy of the set of client IDs in a room.
```

## Background Tasks

```python

@app.task

Decorator to register a coroutine that runs once when the server starts.

@app.schedule(interval: float)

Decorator to register a coroutine that runs periodically every interval seconds.
```

## Plugins

```python
def use(plugin: Callable)

Registers a plugin. The plugin is a callable that takes the app instance and can add routes, middleware, etc.
```

## CORS

```python
def enable_cors(allowed_origins: Optional[List[str]] = None, allow_credentials: bool = False)

Enables CORS globally. Adds the appropriate middleware and response headers.
```

## Server Lifecycle

```python

async def start()

Starts the server (listening on host/port), begins background tasks, and starts the heartbeat.

async def stop()

Stops the server gracefully, closes all WebSocket connections, and cancels background tasks.

def run()

Blocking call that starts the server and waits until interrupted. Sets up signal handlers for graceful shutdown.

Attributes (Internal, Use with Caution)

· _clients: Dict[str, Connection] – active WebSocket clients.
· _rooms: Dict[str, Set[str]] – mapping of room names to client ID sets.
· _handlers: Dict[str, Callable] – WebSocket event handlers.
· _binary_handlers: List[Callable] – binary message handlers.
· _internal_handlers: Dict[str, List[Callable]] – internal event handlers.
· _http_routes: List[Tuple[Pattern, Callable, Set[str]]] – HTTP routes.
· _http_middleware: List[Callable] – HTTP middleware functions.
· _background_tasks: List[Callable] – background task coroutines.
· _scheduled_tasks: List[Tuple[float, Callable]] – scheduled tasks.
· _db: database – primary soketDB instance for logging.
· auto_sync_log: bool – whether automatic logging is enabled.
```