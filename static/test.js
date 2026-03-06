ws = new WebSocket('ws://127.0.0.1:8765');
ws.onopen = () => console.log('connected');
ws.onerror = (e) => console.error(e);