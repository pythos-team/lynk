```markdown
# Performance

Lynkio is designed to be lightweight and efficient for moderate‑scale real‑time applications. This section covers performance characteristics, benchmarks, and tuning tips.

## Benchmarks

*Note: These are rough numbers from a development machine; your mileage may vary.*

- **HTTP requests**: ~10,000‑20,000 req/s (simple "Hello World" response) on a modern laptop.
- **WebSocket messages**: ~5,000‑10,000 messages/s (echo) depending on payload size.
- **Concurrent connections**: Can handle thousands of idle WebSocket connections (limited by file descriptors).

The main limiting factor is Python's asyncio overhead and the GIL. For most real‑time applications (chat, notifications, dashboards), Lynk performs well.

## Factors Affecting Performance

- **Payload size**: Larger messages take longer to serialize/deserialize and transmit.
- **Number of clients in a room**: Broadcasting to many clients can be CPU‑intensive. Lynk batches sends (`room_batch_size`) to mitigate event loop blocking.
- **Logging**: If database logging is enabled, each log insertion runs in a thread executor. While this avoids blocking the loop, too many logs could saturate the executor's queue. Consider reducing log verbosity in production or using a separate logging service.
- **Middleware**: Complex middleware can add latency.

## Tuning Tips

### Increase `room_batch_size`

If you have many clients in a room and you're broadcasting frequently, increase `room_batch_size` to send to more clients per iteration. Monitor the event loop delay.

### Adjust Limits

- `max_payload_size` and `max_message_size` – Set them according to your expected message sizes. Larger limits increase memory usage.
- `max_body_size` – Restrict HTTP body size to prevent abuse.

### Use `uvloop`

You can replace the default asyncio event loop with `uvloop` for a significant performance boost:

```python
import asyncio
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
```

Then run your Lynkio app as usual. (Requires pip install uvloop.)

Profile Your Application

Use asyncio debugging or tools like py-spy to identify bottlenecks.

Disable Logging in Production

If you don't need logs, set auto_sync_log=False or don't create a database. Logging adds overhead.

Load Testing

Use tools like wrk for HTTP and autobahn|testsuite for WebSocket to test your deployment.

Memory Usage

Each WebSocket client connection consumes some memory (a few KB). With max_connections you can limit resource usage. Idle connections are kept alive but consume little CPU.

Scaling Horizontally

Lynk's in‑memory rooms and sessions are not shared across instances. To scale horizontally, you would need to:

· Use a shared pub/sub like Redis (not built‑in).
· Use sticky sessions (if behind a load balancer).
· For logging, each instance writes to its own soketDB database; you can later merge them or use a shared network filesystem (not recommended).

Consider the trade‑offs: Lynk is best suited for single‑node deployments or small clusters where you can accept some data locality.

Next

· API Reference: API