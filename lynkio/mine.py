"""
Lynk – Real‑time event engine (pure Python, standard library only)
"""

import asyncio
import hashlib
import json
import logging
import struct
import time
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set, Tuple, Union

# ----------------------------------------------------------------------
# Exceptions
# ----------------------------------------------------------------------
class StopProcessing(Exception):
    """Raised in middleware to stop further processing of an event."""
    pass

class WebSocketError(Exception):
    """WebSocket protocol error."""
    pass

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
# Connection class
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
# Lynk – main engine
# ----------------------------------------------------------------------
class Lynk:
    """Main event engine. Manages clients, rooms, and message routing."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8765,
        max_payload_size: int = 256 * 1024,  # 256 KiB
        room_batch_size: int = 100,          # for chunked room broadcasts
    ):
        self.host = host
        self.port = port
        self.max_payload_size = max_payload_size
        self.room_batch_size = room_batch_size

        self._clients: Dict[str, Connection] = {}
        self._rooms: Dict[str, Set[str]] = {}
        self._handlers: Dict[str, Callable[[Connection, Any], Awaitable[None]]] = {}
        self._internal_handlers: Dict[
            str, List[Callable[[Optional[Connection], Optional[Any]], Awaitable[None]]]
        ] = {}
        self._middleware: List[
            Callable[[Connection, str, Any], Awaitable[Optional[Any]]]
        ] = []

        self._server: Optional[asyncio.Server] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False
        self._logger = logging.getLogger("Lynk")

    # ------------------------------------------------------------------
    # Public API: decorators
    # ------------------------------------------------------------------
    def on(self, event: str):
        """Register an event handler."""
        def decorator(func: Callable[[Connection, Any], Awaitable[None]]):
            self._handlers[event] = func
            return func
        return decorator

    def on_internal(self, event: str):
        """Register an internal event handler."""
        def decorator(func: Callable[[Optional[Connection], Optional[Any]], Awaitable[None]]):
            self._internal_handlers.setdefault(event, []).append(func)
            return func
        return decorator

    def middleware(self, func):
        """Register middleware."""
        self._middleware.append(func)
        return func

    # ------------------------------------------------------------------
    # Public API: actions
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
        # Process in batches to avoid overwhelming the event loop
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
        """Start the WebSocket server."""
        self._loop = asyncio.get_running_loop()
        self._server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )
        self._running = True
        self._logger.info(f"Lynk listening on ws://{self.host}:{self.port}")

    async def stop(self) -> None:
        """Stop the server and close all client connections."""
        self._running = False
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        close_tasks = [c.close() for c in self._clients.values()]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)
        self._clients.clear()
        self._rooms.clear()
        self._logger.info("Lynk stopped")

    def run(self) -> None:
        """Run the server until interrupted (blocking call – for standalone use only)."""
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        await self.start()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()

    # ------------------------------------------------------------------
    # Client connection handling
    # ------------------------------------------------------------------
    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            await self._handshake(reader, writer)
        except Exception as e:
            self._logger.warning(f"Handshake failed: {e}")
            writer.close()
            await writer.wait_closed()
            return

        client = Connection(reader, writer)
        self._clients[client.id] = client
        self._logger.info(f"Client connected: {client.id}")
        self._dispatch_internal("connect", client)

        try:
            await self._read_messages(client)
        except (ConnectionError, asyncio.CancelledError):
            pass
        finally:
            if client.id in self._clients:
                del self._clients[client.id]
            for room in list(client.rooms):
                self.leave_room(client.id, room)
            self._logger.info(f"Client disconnected: {client.id}")
            self._dispatch_internal("disconnect", client)
            if not client.closed:
                await client.close()

    async def _handshake(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        request_line = await reader.readline()
        if not request_line:
            raise WebSocketError("Empty request")
        self._logger.debug(f"Handshake request: {request_line.decode().strip()}")
        headers = {}
        while True:
            line = await reader.readline()
            if line == b"\r\n":
                break
            if not line:
                raise WebSocketError("Incomplete headers")
            try:
                key, value = line.decode().strip().split(":", 1)
            except ValueError:
                self._logger.warning(f"Malformed header line: {line}")
                raise WebSocketError("Malformed header")
            headers[key.strip().lower()] = value.strip()

        if headers.get("upgrade", "").lower() != "websocket":
            raise WebSocketError("Not a WebSocket upgrade")
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
        self._logger.debug("Handshake successful")

    async def _read_messages(self, client: Connection) -> None:
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
                        break  # need more data

                    # Enforce max payload size
                    if length > self.max_payload_size:
                        self._logger.debug(f"Payload too large ({length} bytes), closing")
                        await client.close(1009, "Payload too large")
                        return

                    buffer = buffer[consumed:]

                    if opcode == 0x8:  # close
                        self._logger.debug(f"Received close frame from {client.id}")
                        await client.close()
                        return
                    elif opcode == 0x9:  # ping
                        self._logger.debug(f"Received ping from {client.id}")
                        await client.send(payload, text=False)  # pong
                        continue
                    elif opcode == 0xA:  # pong
                        self._logger.debug(f"Received pong from {client.id}")
                        continue
                    elif opcode & 0x8:
                        continue

                    if opcode == 0x1:  # text
                        try:
                            message = payload.decode()
                        except UnicodeDecodeError:
                            self._logger.debug("Invalid UTF-8, closing")
                            await client.close(1007, "Invalid UTF-8")
                            return
                        await self._handle_message(client, message)
            except (ConnectionError, asyncio.CancelledError):
                break
            except Exception:
                self._logger.exception("Error in read loop")
                break

    async def _handle_message(self, client: Connection, message: str) -> None:
        # Basic rate‑limit hook (simple counter, can be used in middleware)
        client.session["_msg_count"] = client.session.get("_msg_count", 0) + 1
        # Track last activity for idle detection
        client.session["_last_active"] = time.time()

        try:
            data = json.loads(message)
            event = data.get("event")
            payload = data.get("data", {})
        except json.JSONDecodeError:
            self._logger.debug("Invalid JSON, closing")
            await client.close(1007, "Invalid JSON")
            return

        if not isinstance(event, str):
            self._logger.debug(f"Received message with non-string event: {event}")
            return

        self._logger.debug(f"Received event '{event}' from {client.id} with payload: {payload}")

        # Run middleware chain
        for i, middleware in enumerate(self._middleware):
            try:
                self._logger.debug(f"Running middleware {i} for event '{event}'")
                result = await middleware(client, event, payload)
                if result is not None:
                    payload = result
                    self._logger.debug(f"Middleware {i} modified payload: {payload}")
            except StopProcessing:
                self._logger.debug(f"Middleware {i} stopped processing for event '{event}'")
                return
            except Exception:
                self._logger.exception(f"Middleware {i} error")
                return

        # Dispatch to registered handler
        handler = self._handlers.get(event)
        if handler:
            self._logger.debug(f"Dispatching event '{event}' to handler")
            try:
                await handler(client, payload)
            except Exception:
                self._logger.exception(f"Handler error for event {event}")
        else:
            self._logger.debug(f"No handler registered for event '{event}'")

        # Internal event for received messages
        self._dispatch_internal("message", client, {"event": event, "data": payload})


# ----------------------------------------------------------------------
# Example standalone usage (if run directly)
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Set logging to DEBUG to see all debug messages
    logging.basicConfig(level=logging.DEBUG)
    lynk = Lynk()

    @lynk.on("ping")
    async def on_ping(client, data):
        await lynk.emit("pong", {"echo": data}, client.id)

    lynk.run()