```markdown
# Quickstart

Let's build a simple HTTP and WebSocket server with Lynk. This example will:

- Serve a "Hello World" HTML page.
- Handle a WebSocket connection and echo messages back.

## Create the Application

Create a file `app.py`:

```python
from lynk import Lynk

app = Lynk()

@app.get("/")
async def index(req):
    return """
    <!DOCTYPE html>
    <html>
    <body>
        <h1>Lynk Quickstart</h1>
        <input id="msg" placeholder="Type a message">
        <button onclick="sendMsg()">Send</button>
        <div id="log"></div>
        <script src="/lynkio/client.js></script>
        <script>
            const client = new LynkClient((location.protocol === "https:" ? "wss://" : "ws://") + location.host);
            
            client.onmessage = (e) => {
                document.getElementById('log').innerHTML += '<p>Received: ' + e.data + '</p>';
            };
            async function sendMsg() {
                const msg = document.getElementById('msg').value;
               await client.connect(); client.send(JSON.stringify({event: 'echo', data: {text: msg}}));
            }
        </script>
    </body>
    </html>
    """

@app.on("echo")
async def on_echo(client, data):
    # Echo the received data back to the same client
    await client.send(json.dumps({"event": "echo_reply", "data": data}))
```

Run the Server

```bash
python app.py
```

You'll see output like:

```
Lynk listening on http://0.0.0.0:8765 (WebSocket on same port)
```

Open your browser at http://localhost:8765. Type a message and click "Send". You should see the echoed reply appear on the page.

What Just Happened?

· @app.get("/") registered an HTTP GET handler that returns an HTML page.
· The HTML page opens a WebSocket connection to the same server (path /ws is handled automatically by Lynkio).
· @app.on("echo") registered a WebSocket event handler. When the client sends a JSON message with event: "echo", this function is called, and we send a reply back.

That's it! You've built a real‑time application in a few lines.

Next, explore the Routing guide to learn more about HTTP and WebSocket routing.

```