const UNTITLED = 'Untitled';
const MAX_NEST_DEPTH = 4;

const App = {
    currentWorkspaceId: null,
    workspaces: [],
    sheet: { onSave: null, returnFocus: null },
    _refreshing: false,
    _refreshQueued: false,

    init() {
        this.bindLogin();
        this.bindMain();
        this.bindContextMenu();
        this.bindSheet();
        this.bindGlobalScrollCancel();

        Api.onError = (msg) => this.toast(msg);

        const stored = Api.getStoredToken();
        if (stored) {
            Api.token = stored;
            this.tryConnect();
        } else {
            document.getElementById('login-screen').hidden = false;
        }
    },

    /* ---------- Login ---------- */

    bindLogin() {
        const btn = document.getElementById('login-btn');
        const input = document.getElementById('token-input');
        const error = document.getElementById('login-error');

        const doLogin = async () => {
            const token = input.value.trim();
            if (!token) return;
            Api.setToken(token);
            try {
                await Api.get('/api/workspaces');
                this.showMain();
            } catch (e) {
                error.textContent = 'Invalid token or server unreachable';
                error.hidden = false;
                Api.clearToken();
            }
        };

        btn.addEventListener('click', doLogin);
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') doLogin();
        });
    },

    async tryConnect() {
        try {
            await Api.get('/api/workspaces');
            this.showMain();
        } catch (e) {
            Api.clearToken();
            document.getElementById('login-screen').hidden = false;
            document.getElementById('main-screen').hidden = true;
        }
    },

    showMain() {
        // Pre-apply the expected screen state to avoid a flash before refresh() lands.
        const lastId = parseInt(localStorage.getItem('koto_last_workspace'), 10);
        if (lastId) {
            document.body.classList.add('show-todos');
            document.getElementById('back-btn').hidden = false;
            document.getElementById('add-todo-btn').hidden = false;
            document.getElementById('header-title').textContent = '';
        }
        document.getElementById('login-screen').hidden = true;
        document.getElementById('main-screen').hidden = false;
        Api.onRefresh = () => this.refresh();
        Api.connectWs();
        this.refresh();
    },

    showWorkspacesScreen() {
        document.body.classList.remove('show-todos');
        document.getElementById('back-btn').hidden = true;
        document.getElementById('header-title').textContent = 'Workspaces';
        document.getElementById('close-workspaces-btn').hidden = !this.currentWorkspaceId;
    },

    showTodosScreen() {
        if (!this.currentWorkspaceId) return;
        document.body.classList.add('show-todos');
        document.getElementById('back-btn').hidden = false;
        document.getElementById('close-workspaces-btn').hidden = true;
        const ws = this._findWorkspace(this.currentWorkspaceId);
        document.getElementById('header-title').textContent =
            (ws && ws.description) || UNTITLED;
    },

    /* ---------- Main bindings ---------- */

    bindMain() {
        document.getElementById('back-btn').addEventListener('click', () => this.showWorkspacesScreen());
        document.getElementById('close-workspaces-btn').addEventListener('click', () => this.showTodosScreen());

        document.getElementById('logout-btn').addEventListener('click', () => {
            if (!confirm('Log out?')) return;
            Api.disconnectWs();
            Api.clearToken();
            localStorage.removeItem('koto_last_workspace');
            location.reload();
        });

        document.getElementById('add-workspace-btn').addEventListener('click', (e) => {
            this.openSheet('New workspace', '', e.currentTarget, async (val) => {
                await this._call(() =>
                    Api.post('/api/workspaces', { description: val })
                );
            });
        });

        document.getElementById('add-todo-btn').addEventListener('click', (e) => {
            if (!this.currentWorkspaceId) return;
            this.openSheet('New todo', '', e.currentTarget, async (val) => {
                await this._call(() =>
                    Api.post('/api/todos', {
                        description: val,
                        parent_workspace_id: this.currentWorkspaceId,
                    })
                );
            });
        });
    },

    /* ---------- Refresh / render ---------- */

    async refresh() {
        // Debounce: at most one refresh in flight; queue at most one follow-up.
        if (this._refreshing) {
            this._refreshQueued = true;
            return;
        }
        this._refreshing = true;
        try {
            await this._refreshOnce();
        } finally {
            this._refreshing = false;
            if (this._refreshQueued) {
                this._refreshQueued = false;
                this.refresh();
            }
        }
    },

    async _refreshOnce() {
        const isFirstLoad = this.workspaces.length === 0 && !this._loaded;
        try {
            this.workspaces = (await Api.get('/api/workspaces')) || [];
        } catch (e) {
            this.toast('Failed to load workspaces');
            return;
        }

        if (isFirstLoad) {
            this._loaded = true;
            const ws = this._pickDefaultWorkspace();
            if (ws) {
                await this.selectWorkspace(ws);
                return;
            }
        }

        // If current workspace was deleted, drop it.
        if (this.currentWorkspaceId && !this._findWorkspace(this.currentWorkspaceId)) {
            this.currentWorkspaceId = null;
            localStorage.removeItem('koto_last_workspace');
            document.getElementById('todo-list').innerHTML = '';
            document.getElementById('add-todo-btn').hidden = true;
            this.showWorkspacesScreen();
        }

        // Keep header title in sync if the active workspace was renamed.
        if (this.currentWorkspaceId && document.body.classList.contains('show-todos')) {
            const ws = this._findWorkspace(this.currentWorkspaceId);
            if (ws) {
                document.getElementById('header-title').textContent = ws.description || UNTITLED;
            }
        }

        this.renderWorkspaces();
        if (this.currentWorkspaceId) {
            await this.loadTodos(this.currentWorkspaceId);
        }
    },

    _findWorkspace(id) {
        const walk = (list) => {
            for (const ws of list) {
                if (ws.id === id) return ws;
                const sub = walk(ws.workspaces || []);
                if (sub) return sub;
            }
            return null;
        };
        return walk(this.workspaces);
    },

    _pickDefaultWorkspace() {
        const lastId = parseInt(localStorage.getItem('koto_last_workspace'), 10);
        if (lastId) {
            const found = this._findWorkspace(lastId);
            if (found) return found;
        }
        return this.workspaces[0] || null;
    },

    renderWorkspaces() {
        const list = document.getElementById('workspace-list');
        list.innerHTML = '';
        if (this.workspaces.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.textContent = 'No workspaces yet. Tap + to create one.';
            list.appendChild(empty);
            return;
        }
        this.workspaces.forEach(ws => this._renderWorkspace(ws, list, 0));
    },

    _renderWorkspace(ws, container, depth) {
        const div = document.createElement('div');
        div.className = 'workspace-item' + (ws.id === this.currentWorkspaceId ? ' active' : '');
        div.style.paddingLeft = `${0.75 + depth * 1}rem`;
        div.tabIndex = 0;
        div.setAttribute('role', 'button');
        div.setAttribute('aria-label', `Workspace: ${ws.description || UNTITLED}`);
        div.innerHTML = `
            <span class="ws-icon" aria-hidden="true">${depth === 0 ? '◆' : '·'}</span>
            <span class="ws-name">${this._esc(ws.description || UNTITLED)}</span>
            ${this._renderCounts(ws)}
        `;
        div.addEventListener('click', () => this.selectWorkspace(ws));
        div.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.selectWorkspace(ws);
            }
        });
        this._attachLongPress(div, (e) => this.openWorkspaceMenu(e, ws, div));
        container.appendChild(div);

        if (ws.workspaces) {
            ws.workspaces.forEach(child => this._renderWorkspace(child, container, depth + 1));
        }
    },

    _renderCounts(ws) {
        const total = ws.todo_count;
        if (total === 0) return '';

        const parts = [];
        if (ws.overdue_count > 0) {
            parts.push(`<span class="badge overdue" title="Overdue">!${ws.overdue_count}</span>`);
        }
        if (ws.due_today_count > 0) {
            parts.push(`<span class="badge today" title="Due today">${ws.due_today_count}d</span>`);
        }
        if (ws.pending_count === 0 && total > 0) {
            parts.push(`<span class="badge all-done" title="All done">✓ ${total}</span>`);
        } else {
            parts.push(`<span class="badge" title="Done / Total">${ws.done_count}/${total}</span>`);
        }
        return `<span class="ws-counts">${parts.join('')}</span>`;
    },

    async selectWorkspace(ws) {
        this.currentWorkspaceId = ws.id;
        localStorage.setItem('koto_last_workspace', String(ws.id));
        document.getElementById('add-todo-btn').hidden = false;
        this.renderWorkspaces();
        await this.loadTodos(ws.id);
        this.showTodosScreen();
    },

    async loadTodos(workspaceId) {
        let todos;
        try {
            todos = (await Api.get(`/api/todos/workspace/${workspaceId}`)) || [];
        } catch (e) {
            if (e.status === 404) {
                // Workspace was deleted server-side. Drop selection.
                this.currentWorkspaceId = null;
                localStorage.removeItem('koto_last_workspace');
                document.getElementById('add-todo-btn').hidden = true;
                document.getElementById('todo-list').innerHTML = '';
                this.showWorkspacesScreen();
                return;
            }
            this.toast('Failed to load todos');
            return;
        }
        this.renderTodos(todos);
    },

    renderTodos(todos) {
        const list = document.getElementById('todo-list');
        list.innerHTML = '';
        if (todos.length === 0) {
            const empty = document.createElement('div');
            empty.className = 'empty';
            empty.textContent = 'No todos. Tap + to add one.';
            list.appendChild(empty);
            return;
        }
        todos.forEach(todo => this._renderTodo(todo, list, 0));
    },

    _countTodos(todo) {
        let total = 0, done = 0;
        const walk = (t) => {
            for (const c of t.todos || []) {
                total++;
                if (!c.pending) done++;
                walk(c);
            }
        };
        walk(todo);
        return { total, done };
    },

    _renderTodo(todo, container, depth) {
        const clampedDepth = Math.min(depth, MAX_NEST_DEPTH);
        const div = document.createElement('div');
        const completed = !todo.pending;
        const cls = ['todo-item'];
        if (completed) cls.push('completed');
        if (clampedDepth > 0) cls.push(`nested-${clampedDepth}`);
        div.className = cls.join(' ');
        div.dataset.depth = clampedDepth;
        div.style.setProperty('--depth', clampedDepth);
        div.tabIndex = 0;
        div.setAttribute('role', 'group');

        const counts = this._countTodos(todo);
        const hasChildren = counts.total > 0;
        const pct = hasChildren ? (counts.done / counts.total) * 100 : 0;

        const metaParts = [];
        if (todo.due) {
            const d = new Date(todo.due);
            const overdue = todo.pending && d < new Date();
            metaParts.push(`<span class="due${overdue ? ' overdue' : ''}">${this._esc(this._formatDate(d))}</span>`);
        }
        if (todo.urgency > 1) {
            metaParts.push(`<span class="urgency">${'!'.repeat(Math.min(todo.urgency, 4))}</span>`);
        }
        if (hasChildren) {
            metaParts.push(`<span class="frac">${counts.done}/${counts.total}</span>`);
        }
        const meta = metaParts.length
            ? `<div class="todo-meta">${metaParts.join('')}</div>` : '';

        const progress = hasChildren
            ? `<div class="progress" role="progressbar" aria-valuemin="0" aria-valuemax="${counts.total}" aria-valuenow="${counts.done}"><div class="progress-fill" style="width:${pct}%"></div></div>`
            : '';

        const checkboxLabel = completed ? 'Mark incomplete' : 'Mark complete';
        div.innerHTML = `
            <div class="checkbox${completed ? ' checked' : ''}" role="checkbox" aria-checked="${completed}" aria-label="${checkboxLabel}" tabindex="0"></div>
            <div class="todo-content">
                <div class="todo-desc">${this._esc(todo.description || UNTITLED)}</div>
                ${meta}
                ${progress}
            </div>
        `;

        const checkbox = div.querySelector('.checkbox');
        const onToggle = (e) => {
            e.stopPropagation();
            this.toggleTodo(todo.id);
        };
        checkbox.addEventListener('click', onToggle);
        checkbox.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onToggle(e);
            }
        });

        div.addEventListener('keydown', (e) => {
            if (e.target !== div) return;
            if (e.key === 'Enter') {
                e.preventDefault();
                const rect = div.getBoundingClientRect();
                this.openTodoMenu(
                    { clientX: rect.left + 16, clientY: rect.top + 16 },
                    todo,
                    div
                );
            }
        });

        this._attachLongPress(div, (e) => this.openTodoMenu(e, todo, div));

        container.appendChild(div);

        if (todo.todos) {
            todo.todos.forEach(child => this._renderTodo(child, container, depth + 1));
        }
    },

    async toggleTodo(id) {
        await this._call(() => Api.post(`/api/todos/${id}/toggle`));
    },

    /* ---------- Long-press / right-click ---------- */

    _attachLongPress(el, handler) {
        let timer = null;
        let startX = 0, startY = 0;
        let triggered = false;

        const start = (e) => {
            triggered = false;
            const t = e.touches ? e.touches[0] : e;
            startX = t.clientX;
            startY = t.clientY;
            timer = setTimeout(() => {
                triggered = true;
                if (navigator.vibrate) navigator.vibrate(12);
                handler({ clientX: startX, clientY: startY });
            }, 450);
        };
        const move = (e) => {
            if (!timer) return;
            const t = e.touches ? e.touches[0] : e;
            if (Math.abs(t.clientX - startX) > 8 || Math.abs(t.clientY - startY) > 8) {
                clearTimeout(timer);
                timer = null;
            }
        };
        const cancel = () => {
            if (timer) { clearTimeout(timer); timer = null; }
        };

        // Expose cancel so global scroll listener can clear pending presses.
        if (!el._longPressCancels) el._longPressCancels = [];
        el._longPressCancels.push(cancel);

        el.addEventListener('touchstart', start, { passive: true });
        el.addEventListener('touchmove', move, { passive: true });
        el.addEventListener('touchend', cancel);
        el.addEventListener('touchcancel', cancel);

        el.addEventListener('mousedown', (e) => { if (e.button === 0) start(e); });
        el.addEventListener('mousemove', move);
        el.addEventListener('mouseup', cancel);
        el.addEventListener('mouseleave', cancel);

        el.addEventListener('contextmenu', (e) => {
            e.preventDefault();
            cancel();
            handler({ clientX: e.clientX, clientY: e.clientY });
        });

        // Prevent click after long-press
        el.addEventListener('click', (e) => {
            if (triggered) {
                e.stopPropagation();
                e.preventDefault();
                triggered = false;
            }
        }, true);
    },

    bindGlobalScrollCancel() {
        // Any scroll within either list cancels pending long-press timers (B9).
        const cancelAll = () => {
            document.querySelectorAll('[data-depth], .workspace-item, .todo-item').forEach(el => {
                if (el._longPressCancels) el._longPressCancels.forEach(fn => fn());
            });
        };
        document.getElementById('todo-list').addEventListener('scroll', cancelAll, { passive: true });
        document.getElementById('workspace-list').addEventListener('scroll', cancelAll, { passive: true });
    },

    /* ---------- Context menu ---------- */

    bindContextMenu() {
        const menu = document.getElementById('context-menu');
        document.addEventListener('click', (e) => {
            if (!menu.contains(e.target)) this.closeContextMenu();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.closeContextMenu();
                this.closeSheet();
            }
        });
        window.addEventListener('scroll', () => this.closeContextMenu(), true);
    },

    openTodoMenu(pos, todo, returnFocusEl) {
        const menu = document.getElementById('context-menu');
        menu.innerHTML = `
            <button data-action="add-sub">Add sub-todo</button>
            <button data-action="edit">Edit</button>
            <button data-action="delete" class="danger">Delete</button>
        `;
        menu.querySelector('[data-action="add-sub"]').onclick = () => {
            this.closeContextMenu();
            this.openSheet('Sub-todo', '', returnFocusEl, async (val) => {
                await this._call(() =>
                    Api.post('/api/todos', { description: val, parent_todo_id: todo.id })
                );
            });
        };
        menu.querySelector('[data-action="edit"]').onclick = () => {
            this.closeContextMenu();
            this.openSheet('Edit todo', todo.description || '', returnFocusEl, async (val) => {
                await this._call(() =>
                    Api.patch(`/api/todos/${todo.id}`, { description: val })
                );
            });
        };
        menu.querySelector('[data-action="delete"]').onclick = () => {
            this.closeContextMenu();
            if (confirm(`Delete "${todo.description || UNTITLED}"?`)) {
                this._call(() => Api.del(`/api/todos/${todo.id}`));
            }
        };
        this._showMenu(menu, pos);
    },

    openWorkspaceMenu(pos, ws, returnFocusEl) {
        const menu = document.getElementById('context-menu');
        menu.innerHTML = `
            <button data-action="add-sub">Add sub-workspace</button>
            <button data-action="edit">Rename</button>
            <button data-action="delete" class="danger">Delete</button>
        `;
        menu.querySelector('[data-action="add-sub"]').onclick = () => {
            this.closeContextMenu();
            this.openSheet('Sub-workspace', '', returnFocusEl, async (val) => {
                await this._call(() =>
                    Api.post('/api/workspaces', { description: val, parent_id: ws.id })
                );
            });
        };
        menu.querySelector('[data-action="edit"]').onclick = () => {
            this.closeContextMenu();
            this.openSheet('Rename workspace', ws.description || '', returnFocusEl, async (val) => {
                await this._call(() =>
                    Api.patch(`/api/workspaces/${ws.id}`, { description: val })
                );
            });
        };
        menu.querySelector('[data-action="delete"]').onclick = () => {
            this.closeContextMenu();
            if (confirm(`Delete workspace "${ws.description || UNTITLED}" and all its todos?`)) {
                this._call(() => Api.del(`/api/workspaces/${ws.id}`));
                if (this.currentWorkspaceId === ws.id) {
                    this.currentWorkspaceId = null;
                    localStorage.removeItem('koto_last_workspace');
                    document.getElementById('todo-list').innerHTML = '';
                    document.getElementById('add-todo-btn').hidden = true;
                    this.showWorkspacesScreen();
                }
            }
        };
        this._showMenu(menu, pos);
    },

    _showMenu(menu, pos) {
        menu.hidden = false;
        const rect = menu.getBoundingClientRect();
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        let x = pos.clientX;
        let y = pos.clientY;
        if (x + rect.width > vw - 8) x = vw - rect.width - 8;
        if (y + rect.height > vh - 8) y = vh - rect.height - 8;
        if (x < 8) x = 8;
        if (y < 8) y = 8;
        menu.style.left = `${x}px`;
        menu.style.top = `${y}px`;
        const first = menu.querySelector('button');
        if (first) first.focus();
    },

    closeContextMenu() {
        document.getElementById('context-menu').hidden = true;
    },

    /* ---------- Bottom sheet ---------- */

    bindSheet() {
        document.getElementById('sheet-cancel').addEventListener('click', () => this.closeSheet());
        document.getElementById('sheet-backdrop').addEventListener('click', () => this.closeSheet());
        document.getElementById('sheet-save').addEventListener('click', () => this._saveSheet());
        document.getElementById('sheet-input').addEventListener('keydown', (e) => {
            if (e.key === 'Enter') this._saveSheet();
        });
        // Focus trap: keep Tab inside the sheet while open.
        document.getElementById('sheet').addEventListener('keydown', (e) => {
            if (e.key !== 'Tab') return;
            const focusables = document
                .getElementById('sheet')
                .querySelectorAll(
                    'input:not([disabled]):not([hidden]), button:not([disabled]):not([hidden])'
                );
            if (focusables.length === 0) return;
            const first = focusables[0];
            const last = focusables[focusables.length - 1];
            if (e.shiftKey && document.activeElement === first) {
                e.preventDefault();
                last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
                e.preventDefault();
                first.focus();
            }
        });
    },

    openSheet(title, initialValue, returnFocusEl, onSave) {
        document.getElementById('sheet-title').textContent = title;
        const input = document.getElementById('sheet-input');
        input.value = initialValue || '';
        this.sheet.onSave = onSave;
        this.sheet.returnFocus = returnFocusEl || document.activeElement;
        document.getElementById('sheet-backdrop').hidden = false;
        document.getElementById('sheet').hidden = false;
        requestAnimationFrame(() => input.focus());
    },

    closeSheet() {
        document.getElementById('sheet-backdrop').hidden = true;
        document.getElementById('sheet').hidden = true;
        this.sheet.onSave = null;
        const ret = this.sheet.returnFocus;
        this.sheet.returnFocus = null;
        if (ret && typeof ret.focus === 'function') {
            try { ret.focus(); } catch { /* element may be gone */ }
        }
    },

    async _saveSheet() {
        const val = document.getElementById('sheet-input').value.trim();
        if (!val) return;
        const cb = this.sheet.onSave;
        this.closeSheet();
        if (cb) await cb(val);
    },

    /* ---------- Toast / error wrapper ---------- */

    async _call(fn) {
        try {
            const result = await fn();
            // Server's broadcast skips us via X-Client-Id (avoids echo storms),
            // so we must refresh locally to see our own changes.
            this.refresh();
            return result;
        } catch (e) {
            const msg = (e && e.body && e.body.detail) || (e && e.message) || 'Request failed';
            this.toast(typeof msg === 'string' ? msg : 'Request failed');
            return null;
        }
    },

    toast(message) {
        let host = document.getElementById('toast-host');
        if (!host) {
            host = document.createElement('div');
            host.id = 'toast-host';
            host.setAttribute('role', 'status');
            host.setAttribute('aria-live', 'polite');
            document.body.appendChild(host);
        }
        const t = document.createElement('div');
        t.className = 'toast';
        t.textContent = message;
        host.appendChild(t);
        setTimeout(() => {
            t.classList.add('toast-leaving');
            setTimeout(() => t.remove(), 200);
        }, 2800);
    },

    /* ---------- Helpers ---------- */

    _esc(str) {
        const d = document.createElement('div');
        d.textContent = str;
        return d.innerHTML;
    },

    _formatDate(d) {
        const now = new Date();
        const sameDay = d.toDateString() === now.toDateString();
        const tomorrow = new Date(now); tomorrow.setDate(now.getDate() + 1);
        if (sameDay) return 'Today';
        if (d.toDateString() === tomorrow.toDateString()) return 'Tomorrow';
        const sameYear = d.getFullYear() === now.getFullYear();
        return d.toLocaleDateString(undefined, sameYear
            ? { month: 'short', day: 'numeric' }
            : { year: 'numeric', month: 'short', day: 'numeric' });
    },
};

document.addEventListener('DOMContentLoaded', () => App.init());
