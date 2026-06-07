const Api = {
    token: null,
    baseUrl: '',
    ws: null,
    onRefresh: null,
    onError: null,
    clientId: null,
    _reconnectTimer: null,
    _shouldReconnect: false,
    _reconnectAttempt: 0,

    setToken(token) {
        this.token = token;
        localStorage.setItem('koto_token', token);
    },

    getStoredToken() {
        return localStorage.getItem('koto_token');
    },

    clearToken() {
        this.token = null;
        localStorage.removeItem('koto_token');
    },

    async request(method, path, body = null) {
        const headers = {
            'Authorization': `Bearer ${this.token}`,
            'Content-Type': 'application/json',
        };
        if (this.clientId) headers['X-Client-Id'] = this.clientId;
        const opts = { method, headers };
        if (body !== null && body !== undefined) opts.body = JSON.stringify(body);

        let res;
        try {
            res = await fetch(`${this.baseUrl}${path}`, opts);
        } catch (e) {
            const err = new Error('Network error');
            err.cause = e;
            throw err;
        }
        if (res.status === 401) {
            this.clearToken();
            location.reload();
            return null;
        }
        if (res.status === 204) return null;
        if (!res.ok) {
            const err = new Error(`${res.status} ${res.statusText}`);
            err.status = res.status;
            try { err.body = await res.json(); } catch { /* not JSON */ }
            throw err;
        }
        return res.json();
    },

    get(path) { return this.request('GET', path); },
    post(path, body) { return this.request('POST', path, body); },
    patch(path, body) { return this.request('PATCH', path, body); },
    del(path) { return this.request('DELETE', path); },

    connectWs() {
        this._shouldReconnect = true;

        // Clear any pending reconnect before opening a new socket.
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        if (this.ws) {
            // Detach handlers so the old socket's onclose won't re-arm the
            // reconnect timer and tear down the new socket we're about to open.
            this.ws.onopen = null;
            this.ws.onmessage = null;
            this.ws.onclose = null;
            this.ws.onerror = null;
            try { this.ws.close(); } catch { /* ignore */ }
        }

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const params = new URLSearchParams({ token: this.token });
        if (this.clientId) params.set('client_id', this.clientId);
        const url = `${protocol}//${location.host}/ws?${params.toString()}`;
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            this._reconnectAttempt = 0;
        };

        this.ws.onmessage = (event) => {
            let msg;
            try { msg = JSON.parse(event.data); } catch { return; }
            if (msg.type === 'hello' && msg.client_id) {
                this.clientId = msg.client_id;
                return;
            }
            if (msg.type === 'refresh' && this.onRefresh) {
                this.onRefresh();
            }
        };

        this.ws.onclose = () => {
            if (!this._shouldReconnect) return;
            // Exponential backoff with jitter, capped at 30s.
            const base = Math.min(1000 * Math.pow(2, this._reconnectAttempt), 30000);
            const jitter = Math.random() * 0.3 * base;
            const delay = Math.floor(base + jitter);
            this._reconnectAttempt++;
            this._reconnectTimer = setTimeout(() => this.connectWs(), delay);
        };
    },

    disconnectWs() {
        this._shouldReconnect = false;
        this._reconnectAttempt = 0;
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        if (this.ws) {
            this.ws.onopen = null;
            this.ws.onmessage = null;
            this.ws.onclose = null;
            this.ws.onerror = null;
            try { this.ws.close(); } catch { /* ignore */ }
        }
        this.ws = null;
    },
};
