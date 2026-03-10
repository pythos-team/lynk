"""
Lynk Python client (pure standard library, async)
"""

import asyncio
import hashlib
import json
import struct
import uuid
from typing import Any, Callable, Dict, List, Optional

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

def decode_frame(data: bytes):
    """Decode a single WebSocket frame (simplified for client use)."""
    if len(data) < 2:
        raise WebSocketError("Incomplete frame")
    b1, b2 = data[0], data[1]
    fin = (b1 & 0x80) != 0
    opcode = b1 & 0x0F
    masked = (b2 & 0x80) != 0
    payload_len = b2 & 0x7F

    index = 2
    if payload_len == 126:
        if len(data) < 4:
            raise WebSocketError("Incomplete extended length")
        payload_len = struct.unpack("!H", data[2:4])[0]
        index = 4
    elif payload_len == 127:
        if len(data) < 10:
            raise WebSocketError("Incomplete extended length")
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


class LynkClient:
    """Async Lynk client for Python."""

    def __init__(self, uri: str):
        self.uri = uri
        self.reader: Optional[asyncio.StreamReader] = None
        self.writer: Optional[asyncio.StreamWriter] = None
        self.handlers: Dict[str, Callable] = {}
        self.binary_handlers: List[Callable] = []
        self._listen_task: Optional[asyncio.Task] = None
        self._closing = False

    async def connect(self):
        """Connect to the Lynk server."""
        if not self.uri.startswith("ws://"):
            raise ValueError("Only ws:// scheme supported")
        netloc = self.uri[5:]
        if ":" in netloc:
            host, port_str = netloc.split(":", 1)
            port = int(port_str)
        else:
            host = netloc
            port = 80
        self.reader, self.writer = await asyncio.open_connection(host, port)

        # Send WebSocket handshake
        key = self._generate_key()
        handshake = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
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
        import base64
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
                        await self._send_frame(payload, opcode=0xA)  # pong
                        continue
                    elif opcode == 0xA:  # pong
                        continue
                    elif opcode == 0x1:  # text
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
            except (ConnectionError, asyncio.CancelledError):
                break

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
            # Send close frame
            await self._send_frame(b"", opcode=0x8)
            self.writer.close()
            await self.writer.wait_closed()