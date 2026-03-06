import asyncio
import logging
import sys
import time

# Add the parent directory to path so we can import lynk
sys.path.insert(0, '.')

from lynk.server import Lynk
from lynk.client import LynkClient

# ----------------------------------------------------------------------
# Server setup with handlers for all test features
# ----------------------------------------------------------------------
server = Lynk(host="127.0.0.1", port=9876)

@server.on("join")
async def on_join(client, data):
    room = data["room"]
    server.join_room(client.id, room)
    # Notify others in the room
    await server.emit_to_room(room, "user_joined", {"userId": client.id}, exclude=client.id)
    # Send room info to the joining client
    members = len(server.get_room_clients(room))
    await server.emit("room_info", {"room": room, "members": members}, client.id)

@server.on("leave")
async def on_leave(client, data):
    room = data["room"]
    server.leave_room(client.id, room)
    await server.emit_to_room(room, "user_left", {"userId": client.id})

@server.on("set_session")
async def on_set_session(client, data):
    client.session[data["key"]] = data["value"]
    await server.emit("session_updated", {"key": data["key"], "value": data["value"]}, client.id)

@server.on("test")
async def on_test(client, data):
    # Echo back with ack
    await server.emit("test_ack", {"received": data}, client.id)

# Optional middleware example: log all messages
@server.middleware
async def log_middleware(client, event, payload):
    print(f"[{client.id}] {event}: {payload}")
    return payload  # can modify payload if desired

# ----------------------------------------------------------------------
# Test client behaviour
# ----------------------------------------------------------------------
async def run_client(name, actions):
    client = LynkClient("ws://127.0.0.1:9876")
    received = []

    # Register event handlers (no decorators)
    async def on_room_info(data):
        received.append(("room_info", data))
        print(f"[{name}] Room info: {data}")
    client.on("room_info", on_room_info)

    async def on_user_joined(data):
        received.append(("user_joined", data))
        print(f"[{name}] User joined: {data}")
    client.on("user_joined", on_user_joined)

    async def on_user_left(data):
        received.append(("user_left", data))
        print(f"[{name}] User left: {data}")
    client.on("user_left", on_user_left)

    async def on_session_updated(data):
        received.append(("session_updated", data))
        print(f"[{name}] Session updated: {data}")
    client.on("session_updated", on_session_updated)

    async def on_test_ack(data):
        received.append(("test_ack", data))
        print(f"[{name}] Test ack: {data}")
    client.on("test_ack", on_test_ack)

    await client.connect()
    print(f"[{name}] Connected, ID from server will be assigned")

    for action in actions:
        cmd = action[0]
        if cmd == "join":
            await client.join_room(action[1])
        elif cmd == "leave":
            await client.leave_room(action[1])
        elif cmd == "set_session":
            await client.set_session(action[1], action[2])
        elif cmd == "emit":
            await client.emit(action[1], action[2])
        elif cmd == "sleep":
            await asyncio.sleep(action[1])
        else:
            print(f"[{name}] Unknown command: {cmd}")

    # Allow time for final messages to arrive
    await asyncio.sleep(1)
    await client.close()
    return received

async def test_all():
    # Start server in background
    server_task = asyncio.create_task(server.start())
    await asyncio.sleep(0.5)  # give server time to start

    # Define test scenarios for three clients
    client_actions = {
        "Alice": [
            ("join", "lobby"),
            ("set_session", "color", "blue"),
            ("emit", "test", {"msg": "Hello from Alice"}),
            ("sleep", 2),
            ("leave", "lobby"),
        ],
        "Bob": [
            ("sleep", 0.5),
            ("join", "lobby"),
            ("set_session", "color", "red"),
            ("sleep", 2),
        ],
        "Charlie": [
            ("sleep", 1),
            ("join", "lobby"),
            ("emit", "test", {"msg": "Hello from Charlie"}),
            ("sleep", 1),
        ],
    }

    # Run clients concurrently
    results = await asyncio.gather(*[
        run_client(name, actions) for name, actions in client_actions.items()
    ])

    # Stop server
    server_task.cancel()
    try:
        await server_task
    except asyncio.CancelledError:
        pass

    # Simple validation (can be expanded with assertions)
    print("\n=== TEST SUMMARY ===")
    for name, received in zip(client_actions.keys(), results):
        print(f"{name} received {len(received)} messages:")
        for evt, data in received:
            print(f"  {evt}: {data}")

    print("\nAll tests completed.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_all())