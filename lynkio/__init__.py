"""
Lynk – Real-time event engine with native HTTP routing
Python client and server exports.
"""

# Client exports
from .client import (
    LynkClient,
    WebSocketClient,
    HTTPClient,
    UDPClient,
    WebSocketError,
)

# Server exports
from .server import (
    Lynk,
    Request,
    json_response,
    redirect,
    abort,
    FileResponse,
    StreamingResponse,
    RouteGroup,
    Connection,
    StopProcessing,
    HTTPError,
    encode_frame,
    decode_frame,
    make_handshake_accept,
    render_template,
    send_file,
)

from .soketdb import env

# For backward compatibility, expose the old name if needed
lynkClient = LynkClient