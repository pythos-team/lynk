class LynkClient {
    constructor(url) {
        this.url = url;
        this.ws = null;
        this.handlers = {};
        this.binaryHandlers = [];
        this.connectionPromise = null;
        this._connectResolve = null;
        this._connectReject = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 10;
        this.reconnectDelay = 1000; // initial delay 1 second
        this.shouldReconnect = true;
    }

    connect() {
        // If already connecting or connected, return existing promise
        if (this.connectionPromise) return this.connectionPromise;

        this.connectionPromise = new Promise((resolve, reject) => {
            this._connectResolve = resolve;
            this._connectReject = reject;
        });

        this.ws = new WebSocket(this.url);
        this.ws.binaryType = 'arraybuffer';

        this.ws.onmessage = (event) => {
            if (event.data instanceof ArrayBuffer) {
                const data = new Uint8Array(event.data);
                this.binaryHandlers.forEach(handler => handler(data));
            } else {
                try {
                    const msg = JSON.parse(event.data);
                    const { event: evt, data } = msg;
                    if (this.handlers[evt]) {
                        this.handlers[evt](data);
                    }
                } catch (e) {
                    console.error('Failed to parse message', e);
                }
            }
        };

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
            if (this._connectResolve) {
                this._connectResolve();
                this._connectResolve = null;
                this._connectReject = null;
            }
        };

        this.ws.onclose = (event) => {
            console.log(`WebSocket closed (code: ${event.code})`);
            // If connection was never established, reject the promise
            if (this._connectReject) {
                this._connectReject(new Error('Connection closed before open'));
                this._connectResolve = null;
                this._connectReject = null;
            }
            this.connectionPromise = null;
            this.ws = null;

            if (this.shouldReconnect && this.reconnectAttempts < this.maxReconnectAttempts) {
                const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts);
                this.reconnectAttempts++;
                console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
                setTimeout(() => this.connect(), delay);
            } else if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                console.log('Max reconnect attempts reached');
            }
        };

        this.ws.onerror = (err) => {
            console.error('WebSocket error', err);
            // If connection promise is still pending, reject it
            if (this._connectReject) {
                this._connectReject(err);
                this._connectResolve = null;
                this._connectReject = null;
            }
        };

        return this.connectionPromise;
    }

    on(event, callback) {
        this.handlers[event] = callback;
    }

    onBinary(callback) {
        this.binaryHandlers.push(callback);
    }

    emit(event, data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(JSON.stringify({ event, data }));
        } else {
            console.warn('WebSocket not open, cannot emit', event);
        }
    }

    sendBinary(data) {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            this.ws.send(data);
        } else {
            console.warn('WebSocket not open, cannot send binary');
        }
    }

    joinRoom(room) {
        this.emit('join', { room });
    }

    leaveRoom(room) {
        this.emit('leave', { room });
    }

    setSession(key, value) {
        this.emit('set_session', { key, value });
    }

    close() {
        this.shouldReconnect = false; // prevent reconnection
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.connectionPromise = null;
        this._connectResolve = null;
        this._connectReject = null;
    }
}