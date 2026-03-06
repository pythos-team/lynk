import asyncio
import logging
import os
import time
from lynk.server import Lynk, json_response, render_template, send_file, abort

# ----------------------------------------------------------------------
# Create the Lynk application with some security options
# ----------------------------------------------------------------------
app = Lynk(
    host="127.0.0.1",
    port=8765,
    rate_limit=20,              # max 20 messages per second per client
    max_body_size=1024 * 1024,   # 1 MiB
    debug=True
)

# Enable CORS so a frontend on a different port can connect
app.enable_cors(allowed_origins=["*"], allow_credentials=True)

# ----------------------------------------------------------------------
# HTTP Routes
# ----------------------------------------------------------------------
@app.get("/")
async def index(req):
    """Serve the main chat HTML page."""
    return render_template("index.html", context={"title": "Lynk Chat"})

# Static files (this line is CORRECT – not a decorator)
app.static("/static", "static")

# REST API group
api = app.group("/api")

@api.get("/rooms")
async def list_rooms(req):
    """Return a list of all active rooms (with member counts)."""
    rooms = []
    for room, members in app._rooms.items():
        rooms.append({"name": room, "members": len(members)})
    return json_response(rooms)

@api.get("/room/<room_name>/members")
async def room_members(req, room_name):
    """Return the list of users in a specific room."""
    members = app.get_room_clients(room_name)
    return json_response(list(members))

# ----------------------------------------------------------------------
# WebSocket Events
# ----------------------------------------------------------------------
@app.on("join")
async def on_join(client, data):
    """Client joins a room with a nickname."""
    room = data.get("room", "lobby")
    nickname = data.get("nickname", "Anonymous")
    client.session["nickname"] = nickname
    client.session["room"] = room

    app.join_room(client.id, room)

    # Notify others in the room
    await app.emit_to_room(room, "user_joined", {
        "id": client.id,
        "nickname": nickname
    }, exclude=client.id)

    # Send the list of current members to the new client
    members = []
    for cid in app.get_room_clients(room):
        c = app._clients.get(cid)
        if c:
            members.append({
                "id": cid,
                "nickname": c.session.get("nickname", "Anonymous")
            })
    await app.emit("room_info", {
        "room": room,
        "members": members
    }, client.id)

@app.on("leave")
async def on_leave(client, data):
    """Client leaves the room they are currently in."""
    room = client.session.get("room")
    if not room:
        return
    nickname = client.session.get("nickname", "Anonymous")
    app.leave_room(client.id, room)
    await app.emit_to_room(room, "user_left", {
        "id": client.id,
        "nickname": nickname
    })

@app.on("message")
async def on_message(client, data):
    """Broadcast a chat message to the room."""
    room = client.session.get("room")
    if not room:
        return
    text = data.get("text", "")
    nickname = client.session.get("nickname", "Anonymous")
    await app.emit_to_room(room, "chat", {
        "from": client.id,
        "nickname": nickname,
        "text": text
    }, exclude=client.id)

@app.on_binary
async def on_binary(client, payload):
    """Echo binary data back to the client (for testing)."""
    await client.send(payload, text=False)

# ----------------------------------------------------------------------
# Background Tasks
# ----------------------------------------------------------------------
@app.task
async def print_connections():
    """Background task that logs the number of connected clients every 10 seconds."""
    while True:
        await asyncio.sleep(10)
        print(f"Active WebSocket connections: {len(app._clients)}")

@app.schedule(30)
async def broadcast_server_time():
    """Scheduled task: send server time to all clients in the 'time' room."""
    await app.emit_to_room("time", "server_time", {"time": time.time()})

# ----------------------------------------------------------------------
# Plugin example (optional)
# ----------------------------------------------------------------------
def health_check_plugin(app):
    @app.get("/health")
    async def health(req):
        return "OK"

app.use(health_check_plugin)

# ----------------------------------------------------------------------
# Run the server
# ----------------------------------------------------------------------
if __name__ == "__main__":
    # Ensure directories exist
    os.makedirs("templates", exist_ok=True)
    os.makedirs("static", exist_ok=True)

    # Write a simple index.html template (if not present)
    with open("templates/index.html", "w") as f:
        f.write("""
<!DOCTYPE html>
<html>
<head>
    <title>{{ title }}</title>
    <script src="/static/client.js"></script>
    <style>
        body { font-family: sans-serif; max-width: 800px; margin: 20px auto; }
        #chat { border: 1px solid #ccc; height: 400px; overflow-y: scroll; padding: 10px; }
        #users { list-style: none; padding: 0; }
        #users li { border-bottom: 1px solid #eee; padding: 3px; }
        .my-message { color: blue; }
        .other-message { color: green; }
        .system { color: gray; font-style: italic; }
        .button-group { margin: 5px; }
        button { margin: 2px; }
    </style>
</head>
<body>
    <h1>{{ title }}</h1>
    <div>
        <input id="nickname" placeholder="Nickname" value="User">
        <input id="room" placeholder="Room" value="lobby">
        <button id="connectBtn">Connect</button>
        <button id="disconnectBtn" disabled>Disconnect</button>
        <span id="status">Disconnected</span>
    </div>
    <div class="button-group">
        <button id="joinBtn" disabled>Join Room</button>
        <button id="leaveBtn" disabled>Leave Room</button>
    </div>
    <div id="chat"></div>
    <div>
        <input id="message" placeholder="Type a message..." style="width: 80%;">
        <button id="sendBtn" disabled>Send</button>
        <button id="binaryBtn" disabled>Send Binary Ping</button>
    </div>
    <div>
        <h3>Users in room</h3>
        <ul id="users"></ul>
    </div>

    <script>
        const client = new LynkClient('ws://127.0.0.1:8765');
        const chatDiv = document.getElementById('chat');
        const usersList = document.getElementById('users');
        const statusSpan = document.getElementById('status');
        const connectBtn = document.getElementById('connectBtn');
        const disconnectBtn = document.getElementById('disconnectBtn');
        const joinBtn = document.getElementById('joinBtn');
        const leaveBtn = document.getElementById('leaveBtn');
        const sendBtn = document.getElementById('sendBtn');
        const binaryBtn = document.getElementById('binaryBtn');
        const nicknameInput = document.getElementById('nickname');
        const roomInput = document.getElementById('room');
        const messageInput = document.getElementById('message');

        let currentRoom = null;
        let isConnected = false;

        function setConnected(connected) {
            isConnected = connected;
            connectBtn.disabled = connected;
            disconnectBtn.disabled = !connected;
            joinBtn.disabled = !connected;
            leaveBtn.disabled = !connected;
            sendBtn.disabled = !connected;
            binaryBtn.disabled = !connected;
            statusSpan.textContent = connected ? `Connected to ${currentRoom || '?'}` : 'Disconnected';
            if (!connected) {
                usersList.innerHTML = '';
                currentRoom = null;
            }
        }

        function log(text, className) {
            const div = document.createElement('div');
            div.textContent = text;
            div.className = className || '';
            chatDiv.appendChild(div);
            chatDiv.scrollTop = chatDiv.scrollHeight;
        }

        function updateUserList(users) {
            usersList.innerHTML = '';
            users.forEach(user => {
                const li = document.createElement('li');
                li.textContent = `${user.nickname} (${user.id.substr(0,6)})`;
                usersList.appendChild(li);
            });
        }

        // Event handlers
        client.on('room_info', (data) => {
            currentRoom = data.room;
            statusSpan.textContent = `Connected to ${currentRoom}`;
            log(`* Joined room ${data.room} *`, 'system');
            updateUserList(data.members);
        });

        client.on('user_joined', (data) => {
            log(`* ${data.nickname} joined *`, 'system');
            // In a real app you'd refresh the user list, but we rely on room_info updates
        });

        client.on('user_left', (data) => {
            log(`* ${data.nickname} left *`, 'system');
        });

        client.on('chat', (data) => {
            log(`${data.nickname}: ${data.text}`, 'other-message');
        });

        client.on('server_time', (data) => {
            log(`Server time: ${new Date(data.time * 1000).toLocaleTimeString()}`, 'system');
        });

        client.onBinary((data) => {
            const decoder = new TextDecoder();
            log(`Binary echo: ${decoder.decode(data)}`, 'system');
        });

        // Connect
        connectBtn.addEventListener('click', async () => {
            try {
                await client.connect();
                setConnected(true);
                // Automatically join the specified room
                const nickname = nicknameInput.value || 'Anonymous';
                const room = roomInput.value || 'lobby';
                client.emit('join', { nickname, room });
            } catch (err) {
                log(`Connection failed: ${err}`, 'system');
                setConnected(false);
            }
        });

        // Disconnect
        disconnectBtn.addEventListener('click', () => {
            client.close();
            setConnected(false);
        });

        // Join a different room
        joinBtn.addEventListener('click', () => {
            if (!isConnected) return;
            const nickname = nicknameInput.value || 'Anonymous';
            const room = roomInput.value || 'lobby';
            // If already in a room, leaving is optional; server doesn't auto‑leave previous rooms
            // So we'll leave the current room first, then join the new one
            if (currentRoom) {
                client.emit('leave', {});  // server uses session, no need to send room
            }
            client.emit('join', { nickname, room });
        });

        // Leave current room
        leaveBtn.addEventListener('click', () => {
            if (!isConnected || !currentRoom) return;
            client.emit('leave', {});
            currentRoom = null;
            statusSpan.textContent = 'Connected (no room)';
            usersList.innerHTML = '';
        });

        // Send message
        sendBtn.addEventListener('click', () => {
            const text = messageInput.value.trim();
            if (!text) return;
            client.emit('message', { text });
            log(`You: ${text}`, 'my-message');
            messageInput.value = '';
        });

        // Binary ping
        binaryBtn.addEventListener('click', () => {
            const encoder = new TextEncoder();
            client.sendBinary(encoder.encode('ping'));
        });

        // Initially disconnected
        setConnected(false);
    </script>
</body>
</html>
        """.replace("{{ title }}", "Lynk Chat Demo"))

    # Copy client.js to static folder
    # (In a real setup you'd copy the file; here we assume it's already there)
    print("Make sure lynk/client.js is copied to static/client.js")
    logging.basicConfig(level=logging.INFO)
    app.run()