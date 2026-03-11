const client = new LynkClient('ws://localhost:8765');
await client.connect();

// Send a UDP message (will be routed to the server's UDP handler)
client.sendUdp('/ping', { hello: 'world' });

// You can also listen for any response that the server might send via WebSocket
client.on('udp_response', (data) => {
    console.log('UDP response received:', data);
});