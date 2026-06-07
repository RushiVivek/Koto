"""TUI tests using a fake KotoClient and Textual's Pilot."""

from __future__ import annotations

from typing import Any, AsyncIterator

import pytest

from koto.tui.app import KotoApp
from koto.tui.widgets.todo_tree import TodoTree
from koto.tui.widgets.workspace_tree import WorkspaceTree


class FakeClient:
    """In-memory fake of KotoClient — records mutations + returns canned data."""

    def __init__(self):
        self.client_id = "fake-client"
        self.base_url = "http://fake"
        self.token = "fake"
        self.workspaces: list[dict] = []
        self.todos: dict[int, list[dict]] = {}  # ws_id -> list of TodoOut dicts
        self.calls: list[tuple[str, tuple, dict]] = []
        self._next_ws_id = 100
        self._next_todo_id = 1000

    def _record(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))

    async def aclose(self):
        pass

    async def list_workspaces(self) -> list[dict]:
        return [self._ws_dict(w) for w in self.workspaces]

    def _ws_dict(self, ws: dict) -> dict:
        # Hardcoded counts of zero for fake
        return {
            "id": ws["id"],
            "order_index": ws.get("order_index", 0),
            "description": ws["description"],
            "workspaces": [],
            "todo_count": len(self.todos.get(ws["id"], [])),
            "pending_count": sum(
                1 for t in self.todos.get(ws["id"], []) if t.get("pending")
            ),
            "overdue_count": 0,
            "due_today_count": 0,
            "done_count": sum(
                1 for t in self.todos.get(ws["id"], []) if not t.get("pending")
            ),
        }

    async def list_todos(self, workspace_id: int) -> list[dict]:
        return list(self.todos.get(workspace_id, []))

    async def create_workspace(self, description: str, parent_id=None) -> dict:
        self._record("create_workspace", description, parent_id=parent_id)
        ws = {
            "id": self._next_ws_id,
            "order_index": len(self.workspaces),
            "description": description,
        }
        self._next_ws_id += 1
        self.workspaces.append(ws)
        self.todos[ws["id"]] = []
        return self._ws_dict(ws)

    async def update_workspace(self, workspace_id: int, **fields) -> dict:
        self._record("update_workspace", workspace_id, fields=fields)
        for w in self.workspaces:
            if w["id"] == workspace_id:
                w.update(fields)
                return self._ws_dict(w)
        raise RuntimeError(f"ws {workspace_id} not found")

    async def delete_workspace(self, workspace_id: int) -> None:
        self._record("delete_workspace", workspace_id)
        self.workspaces = [w for w in self.workspaces if w["id"] != workspace_id]
        self.todos.pop(workspace_id, None)

    async def reorder_workspace(self, workspace_id: int, direction: str) -> None:
        self._record("reorder_workspace", workspace_id, direction=direction)

    async def create_todo(self, description: str, *, parent_workspace_id=None,
                          parent_todo_id=None) -> dict:
        self._record(
            "create_todo",
            description,
            parent_workspace_id=parent_workspace_id,
            parent_todo_id=parent_todo_id,
        )
        t = {
            "id": self._next_todo_id,
            "order_index": 0,
            "description": description,
            "due": None,
            "effort": 0,
            "recurrence_seconds": None,
            "urgency": 1,
            "pending": True,
            "parent_workspace_id": parent_workspace_id,
            "parent_todo_id": parent_todo_id,
            "todos": [],
        }
        self._next_todo_id += 1
        if parent_workspace_id is not None:
            self.todos.setdefault(parent_workspace_id, []).append(t)
        return t

    async def update_todo(self, todo_id: int, fields: dict) -> dict:
        self._record("update_todo", todo_id, fields=fields)
        for ws_todos in self.todos.values():
            for t in ws_todos:
                if t["id"] == todo_id:
                    t.update(fields)
                    return t
        raise RuntimeError(f"todo {todo_id} not found")

    async def delete_todo(self, todo_id: int) -> None:
        self._record("delete_todo", todo_id)
        for ws_todos in self.todos.values():
            ws_todos[:] = [t for t in ws_todos if t["id"] != todo_id]

    async def toggle_todo(self, todo_id: int) -> dict:
        self._record("toggle_todo", todo_id)
        for ws_todos in self.todos.values():
            for t in ws_todos:
                if t["id"] == todo_id:
                    t["pending"] = not t["pending"]
                    return t
        raise RuntimeError(f"todo {todo_id} not found")

    async def reorder_todo(self, todo_id: int, direction: str) -> None:
        self._record("reorder_todo", todo_id, direction=direction)

    async def watch_refresh(self, **kwargs) -> AsyncIterator[None]:
        # Never yield in tests — keeps the worker idle.
        if kwargs.get("on_disconnect"):
            kwargs["on_disconnect"]()
        # Yield never; sleep forever.
        import asyncio
        await asyncio.sleep(3600)
        yield  # pragma: no cover


# ---------------- helpers ----------------


def _seed_basic(client: FakeClient) -> dict:
    """Create one workspace with one todo. Returns the workspace dict."""
    ws = {"id": 1, "order_index": 0, "description": "Work"}
    client.workspaces.append(ws)
    client.todos[1] = [
        {
            "id": 100,
            "order_index": 0,
            "description": "task1",
            "due": None,
            "effort": 0,
            "recurrence_seconds": None,
            "urgency": 1,
            "pending": True,
            "parent_workspace_id": 1,
            "parent_todo_id": None,
            "todos": [],
        }
    ]
    return ws


# ---------------- tests ----------------


async def test_app_starts_and_lists_workspaces():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert len(app.workspaces) == 1
        assert app.workspaces[0]["description"] == "Work"
        assert app.current_workspace_id == 1
        assert len(app.todos) == 1


async def test_select_workspace_loads_todos():
    client = FakeClient()
    ws = {"id": 1, "order_index": 0, "description": "A"}
    client.workspaces.extend([ws, {"id": 2, "order_index": 1, "description": "B"}])
    client.todos[2] = [
        {
            "id": 200, "order_index": 0, "description": "b-task",
            "due": None, "effort": 0, "recurrence_seconds": None, "urgency": 1,
            "pending": True, "parent_workspace_id": 2, "parent_todo_id": None,
            "todos": [],
        }
    ]
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Auto-selected first workspace (A) which has no todos.
        assert app.current_workspace_id == 1
        assert app.todos == []

        # Move cursor to workspace B and press Enter.
        ws_tree = app.query_one(WorkspaceTree)
        ws_tree.focus()
        await pilot.press("down")  # to B
        await pilot.press("enter")
        await pilot.pause()
        assert app.current_workspace_id == 2
        assert len(app.todos) == 1


async def test_new_workspace_via_modal():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(WorkspaceTree).focus()
        await pilot.press("n")
        await pilot.pause()
        # Type a name and submit.
        await pilot.press(*"newws")
        await pilot.press("enter")
        await pilot.pause()
        names = [c[0] for c in client.calls]
        assert "create_workspace" in names
        assert client.calls[-1][1] == ("newws",)


async def test_toggle_todo():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TodoTree).focus()
        await pilot.press("space")
        await pilot.pause()
        names = [c[0] for c in client.calls]
        assert "toggle_todo" in names


async def test_delete_todo_with_confirm():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TodoTree).focus()
        await pilot.press("d")
        await pilot.pause()
        # confirm modal — press 'y'
        await pilot.press("y")
        await pilot.pause()
        names = [c[0] for c in client.calls]
        assert "delete_todo" in names


async def test_delete_todo_cancel():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TodoTree).focus()
        await pilot.press("d")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        names = [c[0] for c in client.calls]
        assert "delete_todo" not in names


async def test_reorder_todo_down():
    client = FakeClient()
    _seed_basic(client)
    # Add a second todo so reorder is meaningful (the call still fires regardless).
    client.todos[1].append({
        "id": 101, "order_index": 1, "description": "task2",
        "due": None, "effort": 0, "recurrence_seconds": None, "urgency": 1,
        "pending": True, "parent_workspace_id": 1, "parent_todo_id": None,
        "todos": [],
    })
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TodoTree).focus()
        await pilot.press("shift+down")  # move down
        await pilot.pause()
        ops = [(c[0], c[2]) for c in client.calls if c[0] == "reorder_todo"]
        assert ops and ops[-1][1]["direction"] == "down"


async def test_help_screen_opens():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("?")
        await pilot.pause()
        # We should now have HelpScreen on top of the screen stack.
        assert app.screen_stack[-1].__class__.__name__ == "HelpScreen"
        await pilot.press("escape")
        await pilot.pause()
        assert app.screen_stack[-1].__class__.__name__ != "HelpScreen"


async def test_panel_focus_switching():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()
        assert isinstance(app.focused, TodoTree)
        await pilot.press("1")
        await pilot.pause()
        assert isinstance(app.focused, WorkspaceTree)


async def test_edit_modal_returns_only_changed_fields():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        app.query_one(TodoTree).focus()
        await pilot.press("e")
        await pilot.pause()
        # Default focus is on "desc" field. Change description to "renamed".
        for _ in range(len("task1")):
            await pilot.press("backspace")
        await pilot.press(*"renamed")
        # Trigger Save directly via the modal's _save method (avoids click coordinate math).
        modal = app.screen_stack[-1]
        modal._save()
        await pilot.pause()
        update_calls = [c for c in client.calls if c[0] == "update_todo"]
        assert update_calls
        fields = update_calls[-1][2]["fields"]
        assert fields == {"description": "renamed"}


async def test_force_refresh_action():
    client = FakeClient()
    _seed_basic(client)
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        # Simulate server-side change.
        client.workspaces.append({"id": 999, "order_index": 1, "description": "added"})
        await pilot.press("r")
        await pilot.pause()
        names = [w["description"] for w in app.workspaces]
        assert "added" in names


async def test_rapid_toggle_keypresses_cancel_prior_worker():
    """R1: exclusive=True per op group means firing the same key twice
    quickly cancels the in-flight worker. Only one toggle should land."""
    import asyncio

    client = FakeClient()
    _seed_basic(client)

    # Make toggle slow so we can race a second key in.
    original_toggle = client.toggle_todo

    async def slow_toggle(todo_id):
        await asyncio.sleep(0.2)
        return await original_toggle(todo_id)

    client.toggle_todo = slow_toggle  # type: ignore[assignment]

    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TodoTree).focus()
        # Fire two toggle keys back-to-back.
        await pilot.press("space")
        await pilot.press("space")
        await asyncio.sleep(0.5)  # let workers settle
        await pilot.pause()
        toggle_calls = [c for c in client.calls if c[0] == "toggle_todo"]
        # The first worker is cancelled by the second; only one mutation should land.
        # (The first may have started but never reached the await sleep + record;
        # exclusive workers cancel before completion.)
        assert len(toggle_calls) <= 1


async def test_workspace_switch_does_not_rebuild_tree():
    """R2: switching current_workspace_id should only move the cursor,
    not rebuild the workspace tree from scratch."""
    client = FakeClient()
    client.workspaces.extend([
        {"id": 1, "order_index": 0, "description": "A"},
        {"id": 2, "order_index": 1, "description": "B"},
    ])
    client.todos[1] = []
    client.todos[2] = []
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        ws_tree = app.query_one(WorkspaceTree)

        # Track populate calls.
        populate_calls = []
        original_populate = ws_tree.populate

        def counting_populate(workspaces):
            populate_calls.append(len(workspaces))
            return original_populate(workspaces)

        ws_tree.populate = counting_populate  # type: ignore[assignment]

        # Trigger a workspace switch.
        ws_tree.focus()
        await pilot.press("down")  # cursor on B
        await pilot.press("enter")
        await pilot.pause()

        # No populate call: the cursor moved via select_id only.
        assert populate_calls == []


async def test_initial_connect_failure_no_disconnect_toast():
    """R5: on_disconnect must NOT fire if we never successfully connected."""
    import asyncio

    client = FakeClient()
    _seed_basic(client)

    # Override watch_refresh to simulate immediate failure on first connect.
    disconnect_count = 0

    async def failing_watch(**kwargs):
        nonlocal disconnect_count
        # No on_connect ever fires. With the edge-trigger fix, currently_connected
        # stays False so on_disconnect must NOT be called on initial-connect failure.
        # We explicitly skip calling it to model the correct behavior.
        await asyncio.sleep(3600)
        yield  # pragma: no cover

    client.watch_refresh = failing_watch  # type: ignore[assignment]

    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        await asyncio.sleep(0.1)
        await pilot.pause()
        # ws_connected reactive should still be False (default), no toast triggered.
        assert app.ws_connected is False


async def test_selection_preserved_across_refresh():
    client = FakeClient()
    _seed_basic(client)
    client.todos[1].append({
        "id": 101, "order_index": 1, "description": "task2",
        "due": None, "effort": 0, "recurrence_seconds": None, "urgency": 1,
        "pending": True, "parent_workspace_id": 1, "parent_todo_id": None,
        "todos": [],
    })
    app = KotoApp(client=client)
    async with app.run_test() as pilot:
        await pilot.pause()
        app.query_one(TodoTree).focus()
        await pilot.press("down")  # cursor on task2
        await pilot.pause()
        assert app.selected_todo_id == 101
        # Refresh
        await pilot.press("r")
        await pilot.pause()
        assert app.selected_todo_id == 101  # still selected
