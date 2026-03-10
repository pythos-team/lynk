"""
Lynk – Real‑time event engine with native HTTP routing
Pure Python, standard library only.

Features:
- HTTP routing with path parameters and method shortcuts
- Route groups with prefixes and middleware
- WebSocket event handling (RFC6455) with fragmentation and binary support
- Middleware and room-based pub/sub
- Static file serving with streaming
- Template rendering
- Background tasks and scheduler (cron‑like)
- Connection limits, origin validation, rate limiting
- Automatic heartbeat (ping/pong)
- Graceful shutdown with signal handling
- CORS support
- Plugin system
- CLI entry point
- Clean response API (redirect, json, file streaming, abort)
"""

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
import re
import signal
import socket
import struct
import time
import uuid
import urllib.parse
from collections import deque, defaultdict
from contextvars import ContextVar
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union, Pattern
from soketdb import database, env


"""DATABASE INSTANCE"""

db_instance = None
_databases = None

_auto_sync_log_global = None

# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class StopProcessing(Exception):
    """Raised in middleware to stop further processing of an event."""
    pass

class WebSocketError(Exception):
    """WebSocket protocol error."""
    pass

class HTTPError(Exception):
    """HTTP error (e.g., 404, 405)."""
    def __init__(self, status_code: int, message: str = ""):
        self.status_code = status_code
        self.message = message

# ----------------------------------------------------------------------
# WebSocket frame helpers (RFC6455)
# ----------------------------------------------------------------------
def decode_frame(data: bytes) -> Tuple[bool, int, bool, int, bytes, bytes, int]:
    """
    Decode a single WebSocket frame.
    Returns:
        fin, opcode, masked, payload_length, payload, masking_key, total_consumed
    """
    if len(data) < 2:
        raise WebSocketError("Incomplete frame header")
    b1, b2 = data[0], data[1]
    fin = (b1 & 0x80) != 0
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    payload_len = b2 & 0x7F

    index = 2
    if payload_len == 126:
        if len(data) < 4:
            raise WebSocketError("Incomplete extended payload length")
        payload_len = struct.unpack("!H", data[2:4])[0]
        index = 4
    elif payload_len == 127:
        if len(data) < 10:
            raise WebSocketError("Incomplete extended payload length")
        payload_len = struct.unpack("!Q", data[2:10])[0]
        index = 10

    if masked:
        if len(data) < index + 4:
            raise WebSocketError("Missing masking key")
        masking_key = data[index:index + 4]
        index += 4
    else:
        masking_key = b""

    if len(data) < index + payload_len:
        raise WebSocketError("Incomplete payload")

    payload = data[index:index + payload_len]
    if masked:
        payload = bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))

    total_consumed = index + payload_len
    return fin, opcode, masked, payload_len, payload, masking_key, total_consumed


def encode_frame(payload: bytes, opcode: int = 0x1, fin: bool = True, mask: bool = False) -> bytes:
    """Encode a WebSocket frame."""
    b1 = (0x80 if fin else 0) | (opcode & 0x0F)
    payload_len = len(payload)
    if payload_len < 126:
        b2 = (0x80 if mask else 0) | payload_len
        header = struct.pack("!BB", b1, b2)
    elif payload_len < 65536:
        b2 = (0x80 if mask else 0) | 126
        header = struct.pack("!BBH", b1, b2, payload_len)
    else:
        b2 = (0x80 if mask else 0) | 127
        header = struct.pack("!BBQ", b1, b2, payload_len)

    if mask:
        masking_key = struct.pack("!I", uuid.uuid4().fields[0] & 0xFFFFFFFF)
        masked_payload = bytes(b ^ masking_key[i % 4] for i, b in enumerate(payload))
        return header + masking_key + masked_payload
    else:
        return header + payload


def make_handshake_accept(key: str) -> str:
    """Generate Sec‑WebSocket‑Accept header value."""
    import base64
    GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
    sha1 = hashlib.sha1((key + GUID).encode()).digest()
    return base64.b64encode(sha1).decode()


# ----------------------------------------------------------------------
# HTTP request and response
# ----------------------------------------------------------------------
class Request:
    """Parsed HTTP request with helper methods."""
    def __init__(self, method: str, path: str, headers: Dict[str, str], body: bytes = b"", client_ip: str = ""):
        self.method = method.upper()
        self.path = path
        self.headers = headers
        self.body = body
        self.client_ip = client_ip
        self._json = None
        self._form = None

    @property
    def query_params(self) -> Dict[str, str]:
        """Parse query string into dict."""
        if "?" not in self.path:
            return {}
        query = self.path.split("?", 1)[1]
        return dict(urllib.parse.parse_qsl(query))

    @property
    def cookies(self) -> Dict[str, str]:
        """Parse Cookie header."""
        cookie_str = self.headers.get("cookie", "")
        cookies = {}
        for item in cookie_str.split(";"):
            if "=" in item:
                key, val = item.strip().split("=", 1)
                cookies[key] = val
        return cookies

    async def json(self) -> Any:
        """Parse body as JSON (cached)."""
        if self._json is None:
            self._json = json.loads(self.body)
        return self._json

    async def form(self) -> Dict[str, str]:
        """Parse body as URL-encoded form."""
        if self._form is None:
            self._form = dict(urllib.parse.parse_qsl(self.body.decode()))
        return self._form


def http_response(status_code: int, content_type: str, body: Union[str, bytes]) -> bytes:
    """Build an HTTP response."""
    if isinstance(body, str):
        body = body.encode()
    status_text = {
        200: "OK",
        302: "Found",
        400: "Bad Request",
        403: "Forbidden",
        404: "Not Found",
        405: "Method Not Allowed",
        413: "Payload Too Large",
        429: "Too Many Requests",
        500: "Internal Server Error",
        503: "Service Unavailable",
    }.get(status_code, "Unknown")
    headers = [
        f"HTTP/1.1 {status_code} {status_text}",
        f"Content-Type: {content_type}",
        f"Content-Length: {len(body)}",
        "Connection: close",  # simplified; keep-alive can be added
        "\r\n"
    ]
    return "\r\n".join(headers).encode() + body


def abort(status_code: int, message: str = ""):
    """Raise an HTTP error to be caught by the server."""
    raise HTTPError(status_code, message)


# ----------------------------------------------------------------------
# Connection class (WebSocket client)
# ----------------------------------------------------------------------
class Connection:
    """Represents a single WebSocket client."""
    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        client_id: Optional[str] = None
    ):
        self.reader = reader
        self.writer = writer
        self.id = client_id or str(uuid.uuid4())
        self.session: Dict[str, Any] = {}
        self.rooms: Set[str] = set()
        self._close_requested = False
        # Fragmentation support
        self._fragmented_buffer: Optional[bytearray] = None
        self._fragmented_opcode: Optional[int] = None
        # Heartbeat
        self.last_pong = time.time()
        self.last_ping = 0.0

    async def send(self, payload: Union[str, bytes], text: bool = True) -> None:
        """Send a message to this client."""
        if isinstance(payload, str):
            payload = payload.encode()
        opcode = 0x1 if text else 0x2
        frame = encode_frame(payload, opcode=opcode, mask=False)
        try:
            self.writer.write(frame)
            await self.writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass

    async def ping(self) -> None:
        """Send a ping frame."""
        self.last_ping = time.time()
        ping_payload = b"ping"
        frame = encode_frame(ping_payload, opcode=0x9, mask=False)
        try:
            self.writer.write(frame)
            await self.writer.drain()
        except (ConnectionError, BrokenPipeError):
            pass

    async def close(self, code: int = 1000, reason: str = "") -> None:
        """Send a close frame and close the connection."""
        if self._close_requested:
            return
        self._close_requested = True
        payload = struct.pack("!H", code) + reason.encode()
        frame = encode_frame(payload, opcode=0x8, mask=False)
        try:
            self.writer.write(frame)
            await self.writer.drain()
        except Exception:
            pass
        self.writer.close()
        await self.writer.wait_closed()

    @property
    def closed(self) -> bool:
        return self._close_requested or self.writer.is_closing()


# ----------------------------------------------------------------------
# Response classes / helpers
# ----------------------------------------------------------------------
def redirect(location: str, status: int = 302) -> Dict[str, Any]:
    """Return a redirect response."""
    return {"_redirect": location, "_status": status}

def json_response(data: Any, status: int = 200) -> Dict[str, Any]:
    """Return a JSON response."""
    return {"_json": data, "_status": status}

class FileResponse:
    """Streaming file response."""
    def __init__(self, filepath: str, chunk_size: int = 8192, content_type: Optional[str] = None):
        self.filepath = filepath
        self.chunk_size = chunk_size
        self.content_type = content_type or mimetypes.guess_type(filepath)[0] or "application/octet-stream"
        self.size = os.path.getsize(filepath)

    async def __aiter__(self):
        with open(self.filepath, "rb") as f:
            while chunk := f.read(self.chunk_size):
                yield chunk


class StreamingResponse:
    """Generic streaming response with chunked encoding."""
    def __init__(self, generator, content_type: str = "application/octet-stream"):
        self.generator = generator
        self.content_type = content_type

    async def __aiter__(self):
        async for chunk in self.generator:
            yield chunk


# ----------------------------------------------------------------------
# Route group
# ----------------------------------------------------------------------
class RouteGroup:
    """Group of routes with a common prefix and middleware."""
    def __init__(self, prefix: str, app: 'Lynk'):
        self.prefix = prefix.rstrip("/")
        self.app = app
        self._middleware: List[Callable] = []

    def use(self, middleware: Callable):
        """Add middleware to this group."""
        self._middleware.append(middleware)
        return self

    def route(self, path: str, methods: Optional[List[str]] = None):
        """Register a route within this group."""
        full_path = self.prefix + path
        def decorator(func):
            # Wrap the handler to run group middleware first
            async def wrapped(req, *args, **kwargs):
                # Run group middleware (if any)
                for mw in self._middleware:
                    # Middleware can modify request or return a response early
                    # For simplicity, we assume middleware that returns None or a response
                    # We'll implement a simple middleware that can return a response
                    resp = await mw(req)
                    if resp is not None:
                        return resp
                return await func(req, *args, **kwargs)
            self.app.route(full_path, methods)(wrapped)
            return wrapped
        return decorator

    def get(self, path: str):
        return self.route(path, methods=["GET"])

    def post(self, path: str):
        return self.route(path, methods=["POST"])

    def put(self, path: str):
        return self.route(path, methods=["PUT"])

    def delete(self, path: str):
        return self.route(path, methods=["DELETE"])

    def patch(self, path: str):
        return self.route(path, methods=["PATCH"])


# ----------------------------------------------------------------------
# CORS middleware
# ----------------------------------------------------------------------
def cors_middleware(allowed_origins: Optional[List[str]] = None, allow_credentials: bool = False):
    """Return a middleware that adds CORS headers and handles preflight."""
    allowed = allowed_origins or ["*"]

    async def middleware(req):
        # Handle preflight OPTIONS request
        if req.method == "OPTIONS":
            resp_headers = {
                "Access-Control-Allow-Origin": req.headers.get("origin", "*") if "*" in allowed else allowed[0],
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, PATCH, OPTIONS",
                "Access-Control-Allow-Headers": req.headers.get("access-control-request-headers", "*"),
                "Access-Control-Max-Age": "86400",
            }
            if allow_credentials:
                resp_headers["Access-Control-Allow-Credentials"] = "true"
            # Return a 200 response with no body
            response = "\r\n".join([f"HTTP/1.1 200 OK"] + [f"{k}: {v}" for k, v in resp_headers.items()] + ["", ""])
            return response.encode()
        # For non-OPTIONS, store origin for later use in response
        req._cors_origin = req.headers.get("origin", "*")
        req._cors_credentials = allow_credentials
        return None
    return middleware


# ----------------------------------------------------------------------
# Lynk – main engine (HTTP + WebSocket)
# ----------------------------------------------------------------------
class Lynk:
    """Main event engine. Manages WebSocket clients, rooms, and HTTP routes."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        max_payload_size: int = 256 * 1024,      # 256 KiB per frame
        max_message_size: int = 1024 * 1024,     # 1 MiB total fragmented message
        max_body_size: int = 1024 * 1024,        # 1 MiB HTTP body
        room_batch_size: int = 100,               # for chunked room broadcasts
        max_connections: Optional[int] = None,
        allowed_origins: Optional[List[str]] = None,
        rate_limit: Optional[int] = None,         # messages per second per client
        enable_keep_alive: bool = False,
        debug: bool = False,
        enable_database: bool = False,
        database_config: Optional[dict] = None,
    ):
        self.host = host
        self.enable_database = enable_database
        self.database_config = database_config
        self.port = port
        self.max_payload_size = max_payload_size
        self.max_message_size = max_message_size
        self.max_body_size = max_body_size
        self.room_batch_size = room_batch_size
        self.max_connections = max_connections
        self.allowed_origins = allowed_origins or []
        self.rate_limit = rate_limit
        self.enable_keep_alive = enable_keep_alive
        self.debug = debug

        # WebSocket
        self._clients: Dict[str, Connection] = {}
        self._rooms: Dict[str, Set[str]] = {}
        self._handlers: Dict[str, Callable[[Connection, Any], Awaitable[None]]] = {}
        self._binary_handlers: List[Callable[[Connection, bytes], Awaitable[None]]] = []
        self._internal_handlers: Dict[
            str, List[Callable[[Optional[Connection], Optional[Any]], Awaitable[None]]]
        ] = {}
        self._middleware: List[
            Callable[[Connection, str, Any], Awaitable[Optional[Any]]]
        ] = []

        # HTTP routes: list of (pattern, handler, methods)
        self._http_routes: List[Tuple[Pattern, Callable, Set[str]]] = []

        # HTTP middleware
        self._http_middleware: List[Callable] = []

        # Background tasks
        self._background_tasks: List[Callable[[], Awaitable[None]]] = []
        self._scheduled_tasks: List[Tuple[float, Callable]] = []  # interval, func

        # Rate limiting per client (sliding window)
        self._client_msg_times: Dict[str, deque] = defaultdict(lambda: deque(maxlen=rate_limit or 0))

        # Server state
        self._server: Optional[asyncio.Server] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._logger = logging.getLogger("Lynk")
        if debug:
            self._logger.setLevel(logging.DEBUG)

        # Request ID context
        self.request_id_ctx: ContextVar[str] = ContextVar('request_id', default='')

        # CORS settings (global)
        self.cors_allowed_origins = []
        self.cors_allow_credentials = False
        
    # ------------------------------------------------------------------
    # DATABASE WRAPPER
    def create_database(self, name: str = "lynkio_test_db", create_log_table: bool = False, auto_sync_log: bool = False):
      """Create user database instance"""
      global db_instance
      global _databases
      if self.enable_database:
        config = self.database_config
        if not config:
          config = {
            'primary_storage': 'local',
            'backup_enabled': True,
            'auto_backup_hours': 24,
            'query_cache_enabled': True,
            'auto_sync': True,
            'google_drive_enabled': False,
            'huggingface_enabled': False,
            'aws_s3_enabled': False,
            'dropbox_enabled': False
          }
        db = None
        try:
          db = database(name, config)
          if db:
            db_instance = db
            _databases[name] = db
            if create_log_table:
              db.execute("CREATE TABLE WSS_LOGS ()")
              db.execute("CREATE TABLE HTTP_LOGS ()")
              db.execute("CREATE TABLE RUNTIME_LOGS ()")
            if auto_sync_log:
              global auto_sync_log_global
              auto_sync_log_global = auto_sync_log
            return db
          return db
        except Exception as e:
          print(e)
          return db
      raise Exception("database is not enable.")
          

    # ------------------------------------------------------------------
    # Public API: CORS
    # ------------------------------------------------------------------
    def enable_cors(self, allowed_origins: Optional[List[str]] = None, allow_credentials: bool = False):
        """Enable CORS globally."""
        self.cors_allowed_origins = allowed_origins or ["*"]
        self.cors_allow_credentials = allow_credentials
        # Add the CORS middleware
        mw = cors_middleware(allowed_origins, allow_credentials)
        self._http_middleware.append(mw)

    # ------------------------------------------------------------------
    # Public API: Route groups
    # ------------------------------------------------------------------
    def group(self, prefix: str) -> RouteGroup:
        """Create a route group with a common prefix."""
        return RouteGroup(prefix, self)

    # ------------------------------------------------------------------
    # Public API: WebSocket decorators
    # ------------------------------------------------------------------
    def on(self, event: str):
        """Register an event handler for JSON messages."""
        def decorator(func: Callable[[Connection, Any], Awaitable[None]]):
            self._handlers[event] = func
            return func
        return decorator

    def on_binary(self, func: Callable[[Connection, bytes], Awaitable[None]]):
        """Register a handler for binary WebSocket messages."""
        self._binary_handlers.append(func)
        return func

    def on_internal(self, event: str):
        """Register an internal event handler."""
        def decorator(func: Callable[[Optional[Connection], Optional[Any]], Awaitable[None]]):
            self._internal_handlers.setdefault(event, []).append(func)
            return func
        return decorator

    def middleware(self, func):
        """Register middleware for WebSocket."""
        self._middleware.append(func)
        return func

    # ------------------------------------------------------------------
    # Public API: HTTP decorators (with method shortcuts)
    # ------------------------------------------------------------------
    def route(self, path: str, methods: Optional[List[str]] = None):
        """Base HTTP route decorator."""
        if methods is None:
            methods = ["GET"]
        methods = {m.upper() for m in methods}
        pattern = re.compile(f"^{path}$")  # dynamic parameters handled via regex groups

        def decorator(func: Callable[[Request], Awaitable[Any]]):
            self._http_routes.append((pattern, func, methods))
            return func
        return decorator

    def get(self, path: str):
        return self.route(path, methods=["GET"])

    def post(self, path: str):
        return self.route(path, methods=["POST"])

    def put(self, path: str):
        return self.route(path, methods=["PUT"])

    def delete(self, path: str):
        return self.route(path, methods=["DELETE"])

    def patch(self, path: str):
        return self.route(path, methods=["PATCH"])

    # ------------------------------------------------------------------
    # Public API: Unified route (HTTP + WebSocket) – experimental
    # ------------------------------------------------------------------
    def both(self, path: str):
        """Register a handler for both HTTP GET and WebSocket events on the same path."""
        # For WebSocket, we'll use the path as the event name
        def decorator(func):
            # HTTP part
            @self.get(path)
            async def http_handler(req):
                return await func(req)
            # WebSocket part
            @self.on(path)
            async def ws_handler(client, data):
                # We need to adapt: the function may expect (req) or (client, data)
                # This is tricky; we'll assume the function takes (client, data) for WebSocket
                await func(client, data)
            return func
        return decorator

    # ------------------------------------------------------------------
    # Static file serving
    # ------------------------------------------------------------------
    def static(self, prefix: str, directory: str):
      """Serve static files from a directory under a URL prefix."""
      prefix = prefix.rstrip("/")
      pattern = re.compile(f"^{prefix}/(?P<filepath>.*)$")
      base_abs = os.path.abspath(directory)  # absolute path to static folder

      async def serve_static(req: Request, filepath: str):
        # Security: prevent directory traversal
        full_path = os.path.abspath(os.path.join(directory, filepath))
        if not full_path.startswith(base_abs):
          abort(403, "Forbidden")
        if not os.path.exists(full_path) or os.path.isdir(full_path):
          abort(404, "Not Found")
        return FileResponse(full_path)

      self._http_routes.append((pattern, serve_static, {"GET"}))

    # ------------------------------------------------------------------
    # Background tasks and scheduler
    # ------------------------------------------------------------------
    def task(self, func: Callable[[], Awaitable[None]]):
        """Register a background coroutine to run when the server starts."""
        self._background_tasks.append(func)
        return func

    def schedule(self, interval: float):
        """Decorator to run a coroutine periodically (in seconds)."""
        def decorator(func: Callable[[], Awaitable[None]]):
            self._scheduled_tasks.append((interval, func))
            return func
        return decorator

    # ------------------------------------------------------------------
    # Plugin system
    # ------------------------------------------------------------------
    def use(self, plugin):
        """Register a plugin (a callable that takes the app instance)."""
        plugin(self)

    # ------------------------------------------------------------------
    # Public API: WebSocket actions
    # ------------------------------------------------------------------
    async def emit(self, event: str, data: Any, client_id: Optional[str] = None) -> None:
        """Send to one client or broadcast to all."""
        if client_id is not None:
            client = self._clients.get(client_id)
            if client and not client.closed:
                self._logger.debug(f"Emitting {event} to client {client_id}")
                await client.send(json.dumps({"event": event, "data": data}))
            else:
                self._logger.debug(f"Client {client_id} not found or closed, cannot emit {event}")
        else:
            self._logger.debug(f"Broadcasting {event} to all clients")
            await self.emit_to_all_except(event, data, exclude_ids=[])

    async def emit_to_all_except(self, event: str, data: Any, exclude_ids: List[str]) -> None:
        """Broadcast to all clients except those listed in exclude_ids."""
        message = json.dumps({"event": event, "data": data})
        tasks = [
            c.send(message)
            for cid, c in self._clients.items()
            if not c.closed and cid not in exclude_ids
        ]
        if tasks:
            self._logger.debug(f"Broadcasting {event} to {len(tasks)} clients (excluding {exclude_ids})")
            await asyncio.gather(*tasks, return_exceptions=True)

    async def emit_to_room(
        self, room: str, event: str, data: Any, exclude: Optional[str] = None
    ) -> None:
        """Send an event to all clients in a room (chunked to avoid loop flooding)."""
        if room not in self._rooms:
            self._logger.debug(f"Room {room} does not exist, cannot emit {event}")
            return
        message = json.dumps({"event": event, "data": data})
        client_ids = [cid for cid in self._rooms[room] if cid != exclude]
        if not client_ids:
            self._logger.debug(f"No clients in room {room} to emit {event} (exclude={exclude})")
            return

        self._logger.debug(f"Emitting {event} to room {room} for {len(client_ids)} clients")
        for i in range(0, len(client_ids), self.room_batch_size):
            batch = client_ids[i:i + self.room_batch_size]
            tasks = []
            for cid in batch:
                client = self._clients.get(cid)
                if client and not client.closed:
                    tasks.append(client.send(message))
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    def join_room(self, client_id: str, room: str) -> None:
        """Add a client to a room."""
        client = self._clients.get(client_id)
        if not client or client.closed:
            self._logger.debug(f"Cannot join room {room}: client {client_id} not found or closed")
            return
        self._rooms.setdefault(room, set()).add(client_id)
        client.rooms.add(room)
        self._logger.debug(f"Client {client_id} joined room {room}")
        self._dispatch_internal("subscribe", client, {"room": room})

    def leave_room(self, client_id: str, room: str) -> None:
        """Remove a client from a room."""
        client = self._clients.get(client_id)
        if not client:
            return
        if room in self._rooms:
            self._rooms[room].discard(client_id)
            if not self._rooms[room]:
                del self._rooms[room]
                self._logger.debug(f"Room {room} deleted (empty)")
        client.rooms.discard(room)
        self._logger.debug(f"Client {client_id} left room {room}")
        self._dispatch_internal("unsubscribe", client, {"room": room})

    def get_room_clients(self, room: str) -> Set[str]:
        """Return a copy of the set of client IDs in a room."""
        return self._rooms.get(room, set()).copy()

    # ------------------------------------------------------------------
    # Internal event dispatching
    # ------------------------------------------------------------------
    def _dispatch_internal(
        self, event: str, client: Optional[Connection] = None, data: Optional[Any] = None
    ) -> None:
        """Schedule internal event handlers (fire‑and‑forget)."""
        if event not in self._internal_handlers:
            return
        self._logger.debug(f"Dispatching internal event {event} for client {client.id if client else 'system'}")
        for handler in self._internal_handlers[event]:
            asyncio.create_task(handler(client, data))

    # ------------------------------------------------------------------
    # Server lifecycle
    # ------------------------------------------------------------------
    async def start(self) -> None:
        """Start the server."""
        self._loop = asyncio.get_running_loop()
        self._server = await asyncio.start_server(
            self._handle_connection, self.host, self.port
        )
        self._running = True
        self._logger.info(f"Lynk listening on http://{self.host}:{self.port} (WebSocket on same port)")

        # Start background tasks
        for task in self._background_tasks:
            asyncio.create_task(task())

        # Start scheduled tasks
        for interval, func in self._scheduled_tasks:
            asyncio.create_task(self._run_scheduled(interval, func))

        # Start heartbeat
        asyncio.create_task(self._heartbeat())

    async def _run_scheduled(self, interval: float, func: Callable):
        """Run a scheduled task periodically."""
        while self._running:
            await asyncio.sleep(interval)
            try:
                await func()
            except Exception:
                self._logger.exception("Scheduled task error")

    async def stop(self) -> None:
        """Stop the server gracefully."""
        self._running = False
        self._shutdown_event.set()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        # Send close to all WebSocket clients
        close_tasks = [client.close(1001, "Server shutting down") for client in self._clients.values()]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._clients.clear()
        self._rooms.clear()
        self._logger.info("Lynk stopped")

    def run(self) -> None:
        """Run the server until interrupted (blocking call)."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Signal handlers for graceful shutdown
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        try:
            loop.run_until_complete(self._run_forever())
        finally:
            loop.close()

    async def _run_forever(self) -> None:
        await self.start()
        try:
            await self._shutdown_event.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------
    async def _heartbeat(self):
        """Periodically ping clients and close unresponsive ones."""
        while self._running:
            await asyncio.sleep(30)  # ping interval
            now = time.time()
            for client in list(self._clients.values()):
                if client.closed:
                    continue
                # If no pong for 60 seconds, close
                if now - client.last_pong > 60:
                    self._logger.debug(f"Client {client.id} timed out")
                    await client.close(1001, "Going away")
                else:
                    await client.ping()

    # ------------------------------------------------------------------
    # Connection handling (HTTP / WebSocket dispatcher)
    # ------------------------------------------------------------------
    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        """Handle a new client connection – either HTTP or WebSocket upgrade."""
        # Check connection limit
        if self.max_connections and len(self._clients) >= self.max_connections:
            response = http_response(503, "text/plain", "Server busy")
            writer.write(response)
            await writer.drain()
            writer.close()
            await writer.wait_closed()
            return

        # Get client IP
        client_ip = writer.get_extra_info('peername')
        if client_ip:
            client_ip = client_ip[0]
        else:
            client_ip = ""

        try:
            # Read request line
            request_line = await reader.readline()
            if not request_line:
                writer.close()
                await writer.wait_closed()
                return

            # Parse request line
            parts = request_line.decode().strip().split()
            if len(parts) < 3:
                await self._send_http_error(writer, 400, "Bad Request")
                return
            method, path, version = parts[0], parts[1], parts[2]

            # Read headers
            headers = {}
            while True:
                line = await reader.readline()
                if line == b"\r\n":
                    break
                if not line:
                    await self._send_http_error(writer, 400, "Bad Request")
                    return
                try:
                    key, value = line.decode().strip().split(":", 1)
                    headers[key.strip().lower()] = value.strip()
                except ValueError:
                    await self._send_http_error(writer, 400, "Malformed header")
                    return

            # Check for WebSocket upgrade
            if headers.get("upgrade", "").lower() == "websocket":
                # Origin validation
                origin = headers.get("origin", "")
                if self.allowed_origins and origin not in self.allowed_origins:
                    response = http_response(403, "text/plain", "Origin not allowed")
                    writer.write(response)
                    await writer.drain()
                    writer.close()
                    await writer.wait_closed()
                    return
                # Handle WebSocket handshake and then messages
                try:
                    await self._websocket_handshake(reader, writer, headers)
                except Exception as e:
                    self._logger.warning(f"WebSocket handshake failed: {e}")
                    writer.close()
                    await writer.wait_closed()
                return

            # Handle HTTP request
            content_length = int(headers.get("content-length", 0))
            if content_length > self.max_body_size:
                await self._send_http_error(writer, 413, "Request entity too large")
                return
            body = await reader.read(content_length) if content_length > 0 else b""
            req = Request(method, path, headers, body, client_ip)

            # Run HTTP middleware
            for mw in self._http_middleware:
                try:
                    resp = await mw(req)
                    if resp is not None:
                        # If middleware returns a response, send it and stop
                        if isinstance(resp, bytes):
                            writer.write(resp)
                            await writer.drain()
                        else:
                            await self._send_http_response(writer, resp, req)
                        return
                except Exception as e:
                    self._logger.exception("HTTP middleware error")
                    await self._send_http_error(writer, 500, "Middleware error")
                    return

            # Find matching route
            route_path = path.split("?", 1)[0]
            for pattern, handler, methods in self._http_routes:
                match = pattern.match(route_path)
                if match:
                    if method not in methods:
                        await self._send_http_error(writer, 405, f"Method {method} not allowed")
                        return
                    kwargs = match.groupdict()
                    # Generate request ID
                    request_id = str(uuid.uuid4())
                    self.request_id_ctx.set(request_id)
                    try:
                        result = await handler(req, **kwargs)
                        await self._send_http_response(writer, result, req)
                    except HTTPError as e:
                        await self._send_http_error(writer, e.status_code, e.message)
                    except Exception as e:
                        self._logger.exception(f"HTTP handler error for {method} {path}")
                        await self._send_http_error(writer, 500, "Internal Server Error")
                    break
            else:
                await self._send_http_error(writer, 404, f"Not Found: {route_path}")

        except Exception as e:
            self._logger.exception("Unhandled error in connection handler")
            try:
                await self._send_http_error(writer, 500, "Internal Server Error")
            except:
                pass
        finally:
            # If keep-alive is not enabled, close the connection
            if not self.enable_keep_alive or headers.get("connection", "").lower() != "keep-alive":
                try:
                    writer.close()
                    await writer.wait_closed()
                except:
                    pass

    async def _websocket_handshake(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        headers: Dict[str, str]
    ) -> None:
        """Perform WebSocket handshake and then enter message loop."""
        key = headers.get("sec-websocket-key")
        if not key:
            raise WebSocketError("Missing Sec-WebSocket-Key")
        accept = make_handshake_accept(key)
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept}\r\n"
            "\r\n"
        )
        writer.write(response.encode())
        await writer.drain()
        self._logger.debug("WebSocket handshake successful")

        # Create client and start message loop
        client = Connection(reader, writer)
        self._clients[client.id] = client
        self._logger.info(f"WebSocket client connected: {client.id}")
        self._dispatch_internal("connect", client)

        try:
            await self._read_websocket_messages(client)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            if client.id in self._clients:
                del self._clients[client.id]
            for room in list(client.rooms):
                self.leave_room(client.id, room)
            self._logger.info(f"WebSocket client disconnected: {client.id}")
            self._dispatch_internal("disconnect", client)
            if not client.closed:
                await client.close()

    async def _read_websocket_messages(self, client: Connection) -> None:
        """Read and process WebSocket frames, handling fragmentation."""
        buffer = b""
        while not client.closed:
            try:
                chunk = await client.reader.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while buffer:
                    try:
                        fin, opcode, masked, length, payload, key, consumed = decode_frame(buffer)
                    except WebSocketError as e:
                        self._logger.debug(f"Protocol error, need more data: {e}")
                        break

                    if length > self.max_payload_size:
                        self._logger.debug(f"Payload too large ({length} bytes), closing")
                        await client.close(1009, "Payload too large")
                        return

                    buffer = buffer[consumed:]

                    # Control frames
                    if opcode == 0x8:  # close
                        await client.close()
                        return
                    elif opcode == 0x9:  # ping
                        # Echo payload in pong (RFC6455)
                        await client.send(payload, text=False)  # pong with same payload
                        client.last_pong = time.time()
                        continue
                    elif opcode == 0xA:  # pong
                        client.last_pong = time.time()
                        continue
                    elif opcode & 0x8:  # other control frames
                        continue

                    # Data frames
                    if opcode == 0x0:  # continuation
                        if client._fragmented_buffer is None:
                            self._logger.debug("Unexpected continuation frame")
                            await client.close(1002, "Protocol error")
                            return
                        client._fragmented_buffer.extend(payload)
                        if fin:
                            # Message complete
                            complete_payload = bytes(client._fragmented_buffer)
                            op = client._fragmented_opcode
                            client._fragmented_buffer = None
                            client._fragmented_opcode = None
                            if len(complete_payload) > self.max_message_size:
                                await client.close(1009, "Message too large")
                                return
                            await self._handle_websocket_frame(client, op, complete_payload)
                    else:
                        # New message (text or binary)
                        if client._fragmented_buffer is not None:
                            self._logger.debug("New frame before previous fragmented message finished")
                            await client.close(1002, "Protocol error")
                            return
                        if not fin:
                            # Start fragmented message
                            client._fragmented_buffer = bytearray(payload)
                            client._fragmented_opcode = opcode
                        else:
                            # Single frame message
                            if len(payload) > self.max_message_size:
                                await client.close(1009, "Message too large")
                                return
                            await self._handle_websocket_frame(client, opcode, payload)
            except (ConnectionError, asyncio.CancelledError):
                break
            except Exception:
                self._logger.exception("Error in WebSocket read loop")
                break

    async def _handle_websocket_frame(self, client: Connection, opcode: int, payload: bytes) -> None:
        """Handle a complete WebSocket message (after reassembly if needed)."""
        if opcode == 0x1:  # text
            try:
                message = payload.decode()
            except UnicodeDecodeError:
                await client.close(1007, "Invalid UTF-8")
                return
            await self._handle_websocket_message(client, message)
        elif opcode == 0x2:  # binary
            await self._handle_websocket_binary(client, payload)

    async def _handle_websocket_message(self, client: Connection, message: str) -> None:
        """Handle a WebSocket text message (JSON)."""
        # Rate limiting
        if self.rate_limit:
            now = time.time()
            times = self._client_msg_times[client.id]
            # Remove messages older than 1 second
            while times and times[0] < now - 1:
                times.popleft()
            if len(times) >= self.rate_limit:
                await client.close(1008, "Rate limit exceeded")
                return
            times.append(now)

        client.session["_msg_count"] = client.session.get("_msg_count", 0) + 1
        client.session["_last_active"] = time.time()

        try:
            data = json.loads(message)
            event = data.get("event")
            payload = data.get("data", {})
        except json.JSONDecodeError:
            await client.close(1007, "Invalid JSON")
            return

        if not isinstance(event, str):
            return

        self._logger.debug(f"Received event '{event}' from {client.id} with payload: {payload}")

        # Run middleware chain
        for i, middleware in enumerate(self._middleware):
            try:
                result = await middleware(client, event, payload)
                if result is not None:
                    payload = result
            except StopProcessing:
                return
            except Exception:
                self._logger.exception(f"Middleware {i} error")
                return

        handler = self._handlers.get(event)
        if handler:
            try:
                await handler(client, payload)
            except Exception:
                self._logger.exception(f"Handler error for event {event}")

        self._dispatch_internal("message", client, {"event": event, "data": payload})

    async def _handle_websocket_binary(self, client: Connection, payload: bytes) -> None:
        """Handle a binary WebSocket message."""
        client.session["_last_active"] = time.time()
        for handler in self._binary_handlers:
            try:
                await handler(client, payload)
            except Exception:
                self._logger.exception("Binary handler error")

    # ------------------------------------------------------------------
    # HTTP response helpers
    # ------------------------------------------------------------------
    async def _send_http_response(self, writer: asyncio.StreamWriter, result: Any, req: Request) -> None:
        """Convert handler result to HTTP response and send."""
        # Handle redirect
        if isinstance(result, dict) and "_redirect" in result:
            location = result["_redirect"]
            status = result.get("_status", 302)
            response = (
                f"HTTP/1.1 {status} Found\r\n"
                f"Location: {location}\r\n"
                f"Content-Length: 0\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            )
            writer.write(response.encode())
            await writer.drain()
            return

        # Handle JSON response
        if isinstance(result, dict) and "_json" in result:
            body = json.dumps(result["_json"])
            content_type = "application/json"
            status = result.get("_status", 200)
            # Add CORS headers if enabled
            headers = []
            if self.cors_allowed_origins:
                origin = getattr(req, "_cors_origin", req.headers.get("origin", "*"))
                if origin in self.cors_allowed_origins or "*" in self.cors_allowed_origins:
                    headers.append(f"Access-Control-Allow-Origin: {origin}")
                    if self.cors_allow_credentials:
                        headers.append("Access-Control-Allow-Credentials: true")
            response = http_response(status, content_type, body)
            # Prepend CORS headers if any
            if headers:
                response_lines = response.split(b"\r\n")
                # Insert after status line
                for i, h in enumerate(headers):
                    response_lines.insert(1 + i, h.encode())
                response = b"\r\n".join(response_lines)
            writer.write(response)
            await writer.drain()
            return

        # Handle FileResponse (streaming)
        if isinstance(result, FileResponse):
            headers = [
                f"HTTP/1.1 200 OK",
                f"Content-Type: {result.content_type}",
                f"Content-Length: {result.size}",
                "Connection: close",
            ]
            # Add CORS if enabled
            if self.cors_allowed_origins:
                origin = getattr(req, "_cors_origin", req.headers.get("origin", "*"))
                if origin in self.cors_allowed_origins or "*" in self.cors_allowed_origins:
                    headers.append(f"Access-Control-Allow-Origin: {origin}")
                    if self.cors_allow_credentials:
                        headers.append("Access-Control-Allow-Credentials: true")
            headers.append("\r\n")
            writer.write("\r\n".join(headers).encode())
            await writer.drain()
            async for chunk in result:
                writer.write(chunk)
                await writer.drain()
            return

        # Handle StreamingResponse (chunked)
        if isinstance(result, StreamingResponse):
            headers = [
                f"HTTP/1.1 200 OK",
                f"Content-Type: {result.content_type}",
                "Transfer-Encoding: chunked",
                "Connection: close",
            ]
            if self.cors_allowed_origins:
                origin = getattr(req, "_cors_origin", req.headers.get("origin", "*"))
                if origin in self.cors_allowed_origins or "*" in self.cors_allowed_origins:
                    headers.append(f"Access-Control-Allow-Origin: {origin}")
                    if self.cors_allow_credentials:
                        headers.append("Access-Control-Allow-Credentials: true")
            headers.append("\r\n")
            writer.write("\r\n".join(headers).encode())
            await writer.drain()
            async for chunk in result.generator:
                if chunk:
                    size = f"{len(chunk):X}\r\n".encode()
                    writer.write(size)
                    writer.write(chunk)
                    writer.write(b"\r\n")
                    await writer.drain()
            writer.write(b"0\r\n\r\n")
            await writer.drain()
            return

        # Handle tuple (body, content_type)
        if isinstance(result, tuple) and len(result) == 2:
            body, content_type = result
        elif isinstance(result, str):
            body = result
            content_type = "text/html"
        elif isinstance(result, dict):
            body = json.dumps(result)
            content_type = "application/json"
        elif isinstance(result, bytes):
            body = result
            content_type = "application/octet-stream"
        else:
            body = str(result)
            content_type = "text/plain"

        response = http_response(200, content_type, body)
        # Add CORS if needed
        if self.cors_allowed_origins:
            origin = getattr(req, "_cors_origin", req.headers.get("origin", "*"))
            if origin in self.cors_allowed_origins or "*" in self.cors_allowed_origins:
                # Insert Access-Control header
                response_lines = response.split(b"\r\n")
                cors_line = f"Access-Control-Allow-Origin: {origin}".encode()
                response_lines.insert(1, cors_line)
                if self.cors_allow_credentials:
                    response_lines.insert(2, b"Access-Control-Allow-Credentials: true")
                response = b"\r\n".join(response_lines)
        writer.write(response)
        await writer.drain()

    async def _send_http_error(self, writer: asyncio.StreamWriter, code: int, message: str) -> None:
        """Send an HTTP error response."""
        response = http_response(code, "text/plain", message)
        try:
            writer.write(response)
            await writer.drain()
        except:
            pass
        finally:
            writer.close()
            await writer.wait_closed()


# ----------------------------------------------------------------------
# send_file helper (returns a FileResponse for streaming)
# ----------------------------------------------------------------------
def send_file(filepath: str, base_dir: str = ".", content_type: Optional[str] = None) -> FileResponse:
    """
    Return a FileResponse that streams the file.
    Raises FileNotFoundError if file does not exist or is a directory.
    """
    full_path = os.path.join(base_dir, filepath)
    if not os.path.exists(full_path) or os.path.isdir(full_path):
        raise FileNotFoundError(f"File not found: {full_path}")
    return FileResponse(full_path, content_type=content_type)


# ----------------------------------------------------------------------
# Template rendering helper
# ----------------------------------------------------------------------

def render_template(template_name: str, context: Optional[Dict[str, Any]] = None, template_dir: str = "templates") -> str:
    """
    Render an HTML template with variable substitution.
    Supports nested keys using dot notation, e.g. {{ user.name }}.

    Looks for the template file in `template_dir` (relative to current working directory).
    Variables in the template should be written as `{{ variable }}` or `{{ variable.nested }}`.
    Returns the rendered HTML as a string.
    """
    if context is None:
        context = {}

    template_path = os.path.join(template_dir, template_name)
    try:
        with open(template_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        raise FileNotFoundError(f"Template not found: {template_path}")

    def replace(match):
        expr = match.group(1).strip()
        parts = expr.split('.')
        value = context
        for part in parts:
            if isinstance(value, dict) and part in value:
                value = value[part]
            else:
                # path not found, return the original placeholder unchanged
                return match.group(0)
        return str(value)

    # Pattern matches {{ variable }} with optional dots, allowing spaces inside braces
    pattern = r'{{\s*([^}\s]+(?:\.[^}\s]+)*)\s*}}'
    return re.sub(pattern, replace, content)


# ----------------------------------------------------------------------
# CLI entry point (if module run as script)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Lynk server runner")
    parser.add_argument("app", help="Application module in format 'module:app'")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind")
    parser.add_argument("--port", type=int, default=8765, help="Port to bind")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    args = parser.parse_args()

    # Import the app dynamically
    module_path, app_name = args.app.split(":")
    import importlib
    module = importlib.import_module(module_path)
    app = getattr(module, app_name)

    # Configure logging
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.INFO)

    # Set host/port if app doesn't have them
    if hasattr(app, 'host'):
        app.host = args.host
    if hasattr(app, 'port'):
        app.port = args.port
    if hasattr(app, 'debug'):
        app.debug = args.debug

    app.run()