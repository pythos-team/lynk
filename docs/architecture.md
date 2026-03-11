```markdown
# Architecture

Lynkio is built on Python's `asyncio` and uses a single event loop to handle both HTTP and WebSocket connections. This section explains how it works under the hood.

## Overview

```

```

## Connection Handling

When a client connects, `_handle_connection` is called. It reads the request line and headers, then decides whether this is a WebSocket upgrade or a plain HTTP request.

- **HTTP**: The request is parsed into a `Request` object, passed through HTTP middleware, routed to a handler, and a response is sent.
- **WebSocket**: After a successful handshake, a `Connection` object is created and stored in `self._clients`. Then `_read_websocket_messages` enters a loop that reads frames, reassembles fragmented messages, and dispatches them to the appropriate handler.

## WebSocket Protocol

Lynkio implements the essential parts of RFC6455:

- Frame decoding/encoding (with masking support for incoming frames).
- Fragmentation (continuation frames).
- Ping/Pong for heartbeat.
- Close frame handling.

The maximum frame size is controlled by `max_payload_size`, and the maximum total message size by `max_message_size`.

## Event Dispatching

For text messages, Lynk expects a JSON object with at least an `"event"` field. The event name is used to look up a handler in `self._handlers`. If found, the handler is called with the client and the `"data"` part.

Binary messages are dispatched to all handlers registered with `@app.on_binary`.

Internal events (connect, disconnect, subscribe, unsubscribe, message) are dispatched to handlers registered with `@app.on_internal`. These are fire‑and‑forget; they run as separate tasks.

## Rooms

Rooms are implemented as a dictionary mapping room names to sets of client IDs. When a client joins a room, its ID is added to the set, and the client's `rooms` set is updated. When broadcasting to a room, Lynk chunks the client list into batches (`room_batch_size`) to avoid blocking the event loop while sending many messages.

## Background Tasks and Scheduler

Tasks registered with `@app.task` are started as soon as the server starts. Tasks registered with `@app.schedule` are run in a loop with the given interval. Both run as independent asyncio tasks.

## Database Logging

If enabled, Lynkio uses a thread executor to run soketDB `execute()` calls, because soketDB's operations are synchronous and could block the event loop. Each log insertion (`_log_http`, `_log_websocket`, `_log_runtime`) builds a `INSERT INTO ... DATA = {...}` query and offloads it to an executor.

The `query_database` method also runs in an executor, allowing you to perform complex queries without blocking.

## Middleware

HTTP middleware functions are called in order. They can modify the request or return a response early.

WebSocket middleware are called in order with `(client, event, data)`. They can modify `data` (which is passed to the next middleware and the handler) or raise `StopProcessing` to abort.

## Thread Safety

Lynk uses `asyncio` and is single‑threaded. However, soketDB calls are offloaded to threads. The global `_databases` registry is thread‑safe because it's only accessed from the main thread (queries are offloaded but the lookup happens in the main thread before offloading).

## Next

- Performance considerations: [Performance](performance.md)
```
