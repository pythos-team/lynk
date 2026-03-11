"""
Lynk Python client (pure standard library, async)
Includes WebSocket, HTTP, and UDP clients.
"""

import asyncio
import base64
import json
import struct
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

# ----------------------------------------------------------------------
# WebSocket internals
# ----------------------------------------------------------------------
class WebSocketError(Exception):
    pass

def encode_frame(payload: bytes, opcode: int = 0x1, fin: bool = True, mask: bool = True) -> bytes:
    """Encode a WebSocket frame (client must mask outgoing frames)."""
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

def decode_frame(data: bytes) -> Tuple[bool, int, bytes, bytes]:
    """
    Decode a single WebSocket frame.
    Returns (fin, opcode, payload, remaining_data).
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

    remaining = data[index + payload_len:]
    return fin, opcode, payload, remaining

# ----------------------------------------------------------------------
# WebSocket Client
# ----------------------------------------------------------------------
class WebSocketClient:
    """Async WebSocket client for Lynk."""

    def __init__(self, host: str, port: int, path: str = "/"):
        self.host = host
        self.port = port
        self.path = path
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.handlers: Dict[str, Callable] = {}
        self.binary_handlers: List[Callable] = []
        self._listen_task: Optional[asyncio.Task] = None
        self._closing = False
        self._fragmented_buffer: Optional[bytearray] = None
        self._fragmented_opcode: Optional[int] = None

    async def connect(self):
        """Connect to the WebSocket server."""
        self.reader, self.writer = await asyncio.open_connection(self.host, self.port)

        # Send WebSocket handshake
        key = self._generate_key()
        handshake = (
            f"GET {self.path} HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        self.writer.write(handshake.encode())
        await self.writer.drain()

        # Read response
        line = await self.reader.readline()
        if not line.startswith(b"HTTP/1.1 101"):
            raise WebSocketError("Handshake failed")
        while True:
            line = await self.reader.readline()
            if line == b"\r\n":
                break

        # Start listening for messages
        self._listen_task = asyncio.create_task(self._listen())

    def _generate_key(self) -> str:
        return base64.b64encode(uuid.uuid4().bytes).decode()

    async def _listen(self):
        buffer = b""
        while not self._closing:
            try:
                chunk = await self.reader.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while buffer:
                    try:
                        fin, opcode, payload, buffer = decode_frame(buffer)
                    except WebSocketError:
                        break

                    if opcode == 0x8:  # close
                        await self.close()
                        return
                    elif opcode == 0x9:  # ping
                        await self._send_frame(payload, opcode=0xA)
                        continue
                    elif opcode == 0xA:  # pong
                        continue

                    if opcode == 0x0:  # continuation
                        if self._fragmented_buffer is None:
                            await self.close()
                            return
                        self._fragmented_buffer.extend(payload)
                        if fin:
                            complete = bytes(self._fragmented_buffer)
                            op = self._fragmented_opcode
                            self._fragmented_buffer = None
                            self._fragmented_opcode = None
                            await self._handle_message(op, complete)
                    else:
                        if self._fragmented_buffer is not None:
                            await self.close()
                            return
                        if not fin:
                            self._fragmented_buffer = bytearray(payload)
                            self._fragmented_opcode = opcode
                        else:
                            await self._handle_message(opcode, payload)
            except (ConnectionError, asyncio.CancelledError):
                break

    async def _handle_message(self, opcode: int, payload: bytes):
        if opcode == 0x1:  # text
            try:
                msg = json.loads(payload.decode())
                event = msg.get("event")
                data = msg.get("data", {})
                if event in self.handlers:
                    handler = self.handlers[event]
                    if asyncio.iscoroutinefunction(handler):
                        await handler(data)
                    else:
                        handler(data)
            except Exception:
                pass
        elif opcode == 0x2:  # binary
            for handler in self.binary_handlers:
                if asyncio.iscoroutinefunction(handler):
                    await handler(payload)
                else:
                    handler(payload)

    async def _send_frame(self, payload: bytes, opcode: int = 0x1):
        frame = encode_frame(payload, opcode=opcode, mask=True)
        self.writer.write(frame)
        await self.writer.drain()

    async def emit(self, event: str, data: Any):
        """Send an event to the server."""
        msg = json.dumps({"event": event, "data": data})
        await self._send_frame(msg.encode())

    async def send_binary(self, data: bytes):
        """Send a binary message."""
        await self._send_frame(data, opcode=0x2)

    def on(self, event: str, callback: Callable):
        """Register an event handler."""
        self.handlers[event] = callback

    def on_binary(self, callback: Callable):
        """Register a binary message handler."""
        self.binary_handlers.append(callback)

    async def join_room(self, room: str):
        """Join a room."""
        await self.emit("join", {"room": room})

    async def leave_room(self, room: str):
        """Leave a room."""
        await self.emit("leave", {"room": room})

    async def set_session(self, key: str, value: Any):
        """Store a value in the server-side session."""
        await self.emit("set_session", {"key": key, "value": value})

    async def close(self):
        """Close the connection."""
        self._closing = True
        if self._listen_task:
            self._listen_task.cancel()
        if self.writer:
            await self._send_frame(b"", opcode=0x8)
            self.writer.close()
            await self.writer.wait_closed()

# ----------------------------------------------------------------------
# HTTP Client
# ----------------------------------------------------------------------

class HTTPClient:
    """Async HTTP/1.1 client with security and correctness."""

    def __init__(self, host: str, port: int, ssl: bool = False):
        self.host = host
        self.port = port
        self.ssl = ssl

    async def request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        body: bytes = b""
    ) -> Tuple[int, Dict[str, List[str]], bytes]:
        """
        Perform an HTTP request.

        Returns:
            (status_code, headers_dict, body_bytes)

        Headers are returned as a dict mapping lowercase keys to lists of values.
        This preserves all occurrences of a header (e.g., multiple Set-Cookie).
        """
        # Validate and build request headers
        request_headers = self._build_request_headers(method, path, headers, body)

        # Connect and send
        reader, writer = await asyncio.open_connection(self.host, self.port, ssl=self.ssl)
        try:
            writer.write(request_headers + body)
            await writer.drain()

            # Parse response
            status, resp_headers = await self._parse_response_headers(reader)
            body = await self._read_response_body(reader, resp_headers)

            return status, resp_headers, body
        finally:
            writer.close()
            await writer.wait_closed()

    def _build_request_headers(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]],
        body: bytes
    ) -> bytes:
        """Build the raw HTTP request headers with security checks."""
        # Start with request line and mandatory Host header
        lines = [f"{method} {path} HTTP/1.1", f"Host: {self.host}"]

        # Add user headers with validation
        if headers:
            for key, value in headers.items():
                self._validate_header(key, value)
                lines.append(f"{key}: {value}")

        # Add Content-Length
        lines.append(f"Content-Length: {len(body)}")
        lines.append("")  # empty line before body
        request = "\r\n".join(lines).encode()
        return request

    def _validate_header(self, key: str, value: str):
        """Prevent header injection by rejecting CR/LF characters."""
        if any(c in key for c in "\r\n") or any(c in value for c in "\r\n"):
            raise ValueError(f"Invalid header (contains CR/LF): {key}: {value}")

    async def _parse_response_headers(
        self, reader: asyncio.StreamReader
    ) -> Tuple[int, Dict[str, List[str]]]:
        """Parse status line and headers, returning status and a multi‑value header dict."""
        # Status line
        line = await reader.readline()
        if not line:
            raise ConnectionError("Empty response")
        parts = line.decode().split()
        status = int(parts[1])

        # Headers
        headers = {}
        while True:
            line = await reader.readline()
            if line == b"\r\n":
                break
            key, val = line.decode().strip().split(":", 1)
            key = key.lower().strip()
            val = val.strip()
            # Append to list for this key
            if key in headers:
                headers[key].append(val)
            else:
                headers[key] = [val]
        return status, headers

    async def _read_response_body(
        self, reader: asyncio.StreamReader, headers: Dict[str, List[str]]
    ) -> bytes:
        """Read the response body based on Content-Length or until connection close."""
        content_length_headers = headers.get("content-length", [])
        if content_length_headers:
            content_length = int(content_length_headers[-1])  # use last value if multiple
            if content_length == 0:
                return b""
            # Use readexactly to get exactly the promised number of bytes
            return await reader.readexactly(content_length)
        else:
            # No Content-Length; read until EOF (simplistic, not for chunked encoding)
            return await reader.read()

    # ------------------------------------------------------------------
    # Convenience methods for common HTTP verbs
    # ------------------------------------------------------------------
    async def get(self, path: str, headers: Optional[Dict] = None) -> Tuple[int, Dict[str, List[str]], bytes]:
        return await self.request("GET", path, headers)

    async def post(
        self,
        path: str,
        data: Optional[Union[Dict, bytes]] = None,
        json_data: Optional[Any] = None,
        headers: Optional[Dict] = None,
    ) -> Tuple[int, Dict[str, List[str]], bytes]:
        if json_data is not None:
            body = json.dumps(json_data).encode()
            headers = headers or {}
            headers["Content-Type"] = "application/json"
        elif isinstance(data, dict):
            body = json.dumps(data).encode()
            headers = headers or {}
            headers.setdefault("Content-Type", "application/json")
        elif isinstance(data, bytes):
            body = data
        else:
            body = b""
        return await self.request("POST", path, headers, body)

    async def put(
        self,
        path: str,
        data: Optional[Union[Dict, bytes]] = None,
        json_data: Optional[Any] = None,
        headers: Optional[Dict] = None,
    ) -> Tuple[int, Dict[str, List[str]], bytes]:
        # PUT uses same body handling as POST
        return await self.post(path, data, json_data, headers)  # reusing post logic

    async def delete(
        self,
        path: str,
        headers: Optional[Dict] = None,
    ) -> Tuple[int, Dict[str, List[str]], bytes]:
        return await self.request("DELETE", path, headers)

    async def patch(
        self,
        path: str,
        data: Optional[Union[Dict, bytes]] = None,
        json_data: Optional[Any] = None,
        headers: Optional[Dict] = None,
    ) -> Tuple[int, Dict[str, List[str]], bytes]:
        # PATCH uses same body handling as POST
        return await self.post(path, data, json_data, headers)

    async def head(
        self,
        path: str,
        headers: Optional[Dict] = None,
    ) -> Tuple[int, Dict[str, List[str]], bytes]:
        # HEAD responses typically have no body, but we read if any
        return await self.request("HEAD", path, headers)

    async def options(
        self,
        path: str,
        headers: Optional[Dict] = None,
    ) -> Tuple[int, Dict[str, List[str]], bytes]:
        return await self.request("OPTIONS", path, headers)

# ----------------------------------------------------------------------
# UDP Client
# ----------------------------------------------------------------------
class UDPClient:
    """Simple async UDP client for Lynk."""

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port

    async def send(self, data: bytes, timeout: float = 2) -> Optional[bytes]:
        """Send a UDP datagram and wait for a response (if expected)."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        class Protocol(asyncio.DatagramProtocol):
            def connection_made(self, transport):
                self.transport = transport
                transport.sendto(data)

            def datagram_received(self, data, addr):
                if not future.done():
                    future.set_result(data)

            def error_received(self, exc):
                if not future.done():
                    future.set_exception(exc)

        transport, _ = await loop.create_datagram_endpoint(
            Protocol, remote_addr=(self.host, self.port)
        )
        try:
            return await asyncio.wait_for(future, timeout)
        except asyncio.TimeoutError:
            return None
        finally:
            transport.close()

# ----------------------------------------------------------------------
# Unified Lynk Client
# ----------------------------------------------------------------------
class LynkClient:
    """
    Unified client for Lynk server.
    
    Usage:
        client = LynkClient("localhost", 8765)
        # WebSocket
        await client.ws.connect()
        await client.ws.emit("ping", {})
        
        # HTTP
        status, headers, body = await client.http.get("/")
        
        # UDP
        await client.udp.send(json.dumps({"path": "/ping"}).encode())
    """

    def __init__(self, host: str, port: int, ssl: bool = False):
        self.host = host
        self.port = port
        self.ssl = ssl
        self.ws = WebSocketClient(host, port)
        self.http = HTTPClient(host, port, ssl)
        self.udp = UDPClient(host, port)

    @classmethod
    def from_uri(cls, uri: str):
        """Create a client from a URI (e.g., http://localhost:8765 or ws://localhost:8765)."""
        parsed = urlparse(uri)
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if parsed.scheme in ("wss", "https") else 80)
        ssl = parsed.scheme in ("wss", "https")
        return cls(host, port, ssl)