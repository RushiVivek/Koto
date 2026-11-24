"""KotoApp: the Textual TUI."""

from __future__ import annotations

import asyncio
from typing import Optional

from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal
from textual.reactive import reactive
from textual.widgets import Footer, Header, Static, Tree
from textual.widgets._header import HeaderClock

from .client import KotoApiError, KotoClient
from .screens.confirm_modal import ConfirmModal
from .screens.help import HelpScreen
from .screens.input_modal import InputModal
from .screens.todo_edit import TodoEditModal
from .state import UiState
from .widgets.todo_tree import TodoTree
from .widgets.workspace_tree import WorkspaceTree


class _HeaderDateClock(HeaderClock):
    """Override the built-in clock to also show the date.

    The default Textual HeaderClock truncates to .time() before formatting,
    so a date format like "%a %b %d %H:%M" silently loses the date. We
    render off the full datetime instead, and widen the slot so the date
    actually fits.
    """

    DEFAULT_CSS = """
    _HeaderDateClock {
        dock: right;
        width: 24;
        padding: 0 1;
        background: $foreground-darken-1 5%;
        color: $foreground;
        text-opacity: 85%;
        content-align: center middle;
    }
    """

    def render(self):
        from rich.text import Text
        return Text(datetime.now().strftime(self.time_format))


class _DateHeader(Header):
    """Header that renders our date+time clock instead of the time-only one."""

    def __init__(self, show_clock: bool, *, time_format: str | None = None):
        # Always tell the parent NOT to render its own clock; we add ours.
        super().__init__(show_clock=False)
        self._show_date_clock = show_clock
        self._date_time_format = time_format or "%a %b %d  %H:%M"

    def compose(self) -> ComposeResult:
        from textual.widgets._header import (
            HeaderIcon,
            HeaderTitle,
            HeaderClockSpace,
        )
        yield HeaderIcon().data_bind(Header.icon)
        yield HeaderTitle()
        if self._show_date_clock:
            clock = _HeaderDateClock()
            clock.time_format = self._date_time_format
            yield clock
        else:
            yield HeaderClockSpace()


class KotoApp(App):
    CSS_PATH = "styles.tcss"
    TITLE = "koto"

    BINDINGS = [
        Binding("?", "help", "Help", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("r", "force_refresh", "Refresh", show=False),
        Binding("1", "focus_workspaces", "Workspaces", show=False),
        Binding("2", "focus_todos", "Todos", show=False),
    ]

    workspaces: reactive[list[dict]] = reactive(list)
    todos: reactive[list[dict]] = reactive(list)
    current_workspace_id: reactive[Optional[int]] = reactive(None)
    selected_todo_id: reactive[Optional[int]] = reactive(None)
    ws_connected: reactive[bool] = reactive(False)
    # Reactive so cut-styling rerenders when changed.
    clipboard_cut_id: reactive[Optional[int]] = reactive(None)

    def __init__(
        self,
        client: KotoClient,
        *,
        theme: str = "textual-dark",
        show_clock: bool = False,
        confirm_delete: bool = True,
        default_workspace_id: Optional[int] = None,
        state_path: Optional[Path] = None,
    ):
        super().__init__()
        self.client = client
        self._refreshing = False
        self._refresh_queued = False
        self._toast_clear_handle = None
        self._initial_theme = theme
        self._show_clock = show_clock
        self._confirm_delete = confirm_delete
        self._default_workspace_id = default_workspace_id
        # Fold state; persisted only when a path is given.
        self._ui_state = UiState(state_path)
        # Clipboard for todo cut/copy/paste. `_clipboard` holds the todo
        # subtree snapshot; `_clipboard_op` is "cut" or "copy"; the
        # reactive `clipboard_cut_id` mirrors the cut id for rendering.
        self._clipboard: Optional[dict] = None
        self._clipboard_op: Optional[str] = None

    # ---------- compose / mount ----------

    def compose(self) -> ComposeResult:
        yield _DateHeader(show_clock=self._show_clock)
        with Horizontal(id="main"):
            yield WorkspaceTree(id="workspace-tree", state=self._ui_state)
            yield TodoTree(id="todo-tree", state=self._ui_state)
        yield Static("", id="toast")
        yield Footer()

    async def on_mount(self) -> None:
        # Apply configured theme if it's known; fall back silently otherwise.
        if self._initial_theme and self._initial_theme in self._registered_themes:
            self.theme = self._initial_theme
        if self._default_workspace_id is not None:
            self.current_workspace_id = self._default_workspace_id
        self.query_one(WorkspaceTree).focus()
        await self._refresh()
        self._start_ws_worker()

    async def on_unmount(self) -> None:
        try:
            await self.client.aclose()
        except Exception:
            pass

    def get_system_commands(self, screen):
        # Drop the "Maximize"/"Minimize" entry from the command palette;
        # we always want both panels visible side-by-side.
        for cmd in super().get_system_commands(screen):
            if cmd.title in ("Maximize", "Minimize"):
                continue
            yield cmd

    # ---------- refresh ----------

    async def _refresh(self) -> None:
        """Re-fetch workspaces and todos. Debounced: at most one in flight."""
        if self._refreshing:
            self._refresh_queued = True
            return
        self._refreshing = True
        try:
            await self._refresh_once()
        finally:
            self._refreshing = False
            if self._refresh_queued:
                self._refresh_queued = False
                self.call_later(self._refresh)

    async def _refresh_once(self) -> None:
        try:
            self.workspaces = await self.client.list_workspaces()
        except KotoApiError as e:
            self._toast(f"Failed to load workspaces: {e.detail}")
            return

        # Default workspace selection: first one if none selected.
        if self.current_workspace_id is None and self.workspaces:
            self.current_workspace_id = self.workspaces[0]["id"]

        # If current workspace was deleted server-side, drop selection.
        if self.current_workspace_id is not None and not self._find_workspace(
            self.current_workspace_id
        ):
            self.current_workspace_id = None
            self.todos = []
            return

        if self.current_workspace_id is not None:
            try:
                self.todos = await self.client.list_todos(self.current_workspace_id)
            except KotoApiError as e:
                if e.status == 404:
                    self.current_workspace_id = None
                    self.todos = []
                else:
                    self._toast(f"Failed to load todos: {e.detail}")

    def _find_workspace(self, ws_id: int) -> Optional[dict]:
        def walk(items):
            for w in items:
                if w["id"] == ws_id:
                    return w
                found = walk(w.get("workspaces") or [])
                if found:
                    return found
            return None
        return walk(self.workspaces)

    def _find_workspace_parent_id(self, ws_id: int) -> Optional[int]:
        """Return the id of the workspace whose `workspaces` list contains
        `ws_id`, or None if it's at the top level."""
        def walk(items, parent_id):
            for w in items:
                if w["id"] == ws_id:
                    return parent_id
                found = walk(w.get("workspaces") or [], w["id"])
                if found is not None:
                    return found
            return None
        return walk(self.workspaces, None)

    # ---------- watchers ----------

    def watch_workspaces(self, _old, new: list[dict]) -> None:
        try:
            tree = self.query_one(WorkspaceTree)
        except Exception:
            return
        tree.populate(new)
        if self.current_workspace_id is not None:
            tree.select_id(self.current_workspace_id)

    def watch_todos(self, _old, new: list[dict]) -> None:
        try:
            tree = self.query_one(TodoTree)
        except Exception:
            return
        tree.populate(new)
        if self.selected_todo_id is not None:
            tree.select_id(self.selected_todo_id)

    def watch_current_workspace_id(self, _old, _new) -> None:
        # Move the workspace tree's cursor; data hasn't changed so no rebuild.
        try:
            tree = self.query_one(WorkspaceTree)
        except Exception:
            return
        if self.current_workspace_id is not None:
            tree.select_id(self.current_workspace_id)

    def watch_ws_connected(self, _old, new: bool) -> None:
        if not new:
            self._toast("WebSocket disconnected — retrying…")

    def watch_clipboard_cut_id(self, _old, new) -> None:
        try:
            self.query_one(TodoTree).set_cut_id(new)
        except Exception:
            pass

    # ---------- toast ----------

    def _toast(self, message: str, *, info: bool = False) -> None:
        """Show a transient message. info=True for info (blue); default red for errors."""
        try:
            t = self.query_one("#toast", Static)
        except Exception:
            return
        t.update(message)
        t.add_class("visible")
        t.set_class(info, "info")
        if self._toast_clear_handle:
            self._toast_clear_handle.stop()
        self._toast_clear_handle = self.set_timer(3.5, lambda: t.remove_class("visible"))

    # ---------- app-wide actions ----------

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    async def action_force_refresh(self) -> None:
        await self._refresh()

    def action_focus_workspaces(self) -> None:
        self.query_one(WorkspaceTree).focus()

    def action_focus_todos(self) -> None:
        self.query_one(TodoTree).focus()

    # ---------- workspace operations ----------

    async def action_workspace_op(self, op: str) -> None:
        tree = self.query_one(WorkspaceTree)
        current = tree.current

        if op == "open":
            if current:
                self.current_workspace_id = current["id"]
                self.selected_todo_id = None
                await self._refresh()
                self.query_one(TodoTree).focus()

        elif op == "new":
            # Sibling-of-cursor: same parent as the highlighted workspace.
            sibling_parent_id = (
                self._find_workspace_parent_id(current["id"]) if current else None
            )
            name = await self.push_screen_wait(InputModal("New workspace"))
            if name:
                await self._call(
                    lambda: self.client.create_workspace(
                        name, parent_id=sibling_parent_id
                    )
                )

        elif op == "new_sub":
            if not current:
                return
            name = await self.push_screen_wait(InputModal("New sub-workspace"))
            if name:
                await self._call(
                    lambda: self.client.create_workspace(name, parent_id=current["id"])
                )

        elif op == "edit":
            if not current:
                return
            name = await self.push_screen_wait(
                InputModal("Rename workspace", initial=current.get("description") or "")
            )
            if name and name != (current.get("description") or ""):
                await self._call(
                    lambda: self.client.update_workspace(
                        current["id"], description=name
                    )
                )

        elif op == "delete":
            if not current:
                return
            if self._confirm_delete:
                confirmed = await self.push_screen_wait(
                    ConfirmModal(
                        f'Delete workspace "{current.get("description") or "Untitled"}" '
                        f"and all its todos?"
                    )
                )
                if not confirmed:
                    return
            if self.current_workspace_id == current["id"]:
                self.current_workspace_id = None
                self.selected_todo_id = None
            await self._call(lambda: self.client.delete_workspace(current["id"]))

        elif op == "reorder_down":
            if current:
                await self._call(
                    lambda: self.client.reorder_workspace(current["id"], "down")
                )
        elif op == "reorder_up":
            if current:
                await self._call(
                    lambda: self.client.reorder_workspace(current["id"], "up")
                )

    # ---------- todo operations ----------

    async def action_todo_op(self, op: str) -> None:
        tree = self.query_one(TodoTree)
        current = tree.current

        if op == "toggle":
            if current:
                await self._call(lambda: self.client.toggle_todo(current["id"]))

        elif op == "new":
            if self.current_workspace_id is None:
                return
            # Sibling-of-cursor: same parent (workspace OR parent todo) as
            # the highlighted todo. With no cursor, top-level in workspace.
            if current:
                parent_ws = current.get("parent_workspace_id")
                parent_td = current.get("parent_todo_id")
            else:
                parent_ws = self.current_workspace_id
                parent_td = None
            name = await self.push_screen_wait(InputModal("New todo"))
            if name:
                await self._call(
                    lambda: self.client.create_todo(
                        name,
                        parent_workspace_id=parent_ws,
                        parent_todo_id=parent_td,
                    )
                )

        elif op == "new_sub":
            if not current:
                return
            name = await self.push_screen_wait(InputModal("New sub-todo"))
            if name:
                await self._call(
                    lambda: self.client.create_todo(name, parent_todo_id=current["id"])
                )

        elif op == "edit":
            if not current:
                return
            changes = await self.push_screen_wait(TodoEditModal(current))
            if changes:
                await self._call(
                    lambda: self.client.update_todo(current["id"], changes)
                )

        elif op == "delete":
            if not current:
                return
            if self._confirm_delete:
                confirmed = await self.push_screen_wait(
                    ConfirmModal(
                        f'Delete todo "{current.get("description") or "Untitled"}"?'
                    )
                )
                if not confirmed:
                    return
            await self._call(lambda: self.client.delete_todo(current["id"]))

        elif op == "cut":
            if current:
                self._clipboard = current
                self._clipboard_op = "cut"
                self.clipboard_cut_id = current["id"]

        elif op == "copy":
            if current:
                self._clipboard = current
                self._clipboard_op = "copy"
                self.clipboard_cut_id = None

        elif op == "paste":
            await self._paste_clipboard(current, as_child=False)

        elif op == "paste_child":
            await self._paste_clipboard(current, as_child=True)

        elif op == "sort_completed":
            # Sort the cursor's siblings — i.e., the parent's children.
            if current and current.get("parent_todo_id"):
                parent_id = current["parent_todo_id"]
                await self._call(
                    lambda: self.client.sort_todo_completed(parent_id)
                )
            elif self.current_workspace_id is not None:
                ws_id = self.current_workspace_id
                await self._call(
                    lambda: self.client.sort_workspace_completed(ws_id)
                )

        elif op == "reorder_down":
            if current:
                await self._call(
                    lambda: self.client.reorder_todo(current["id"], "down")
                )
        elif op == "reorder_up":
            if current:
                await self._call(
                    lambda: self.client.reorder_todo(current["id"], "up")
                )

    async def _paste_clipboard(
        self, cursor_todo: Optional[dict], *, as_child: bool
    ) -> None:
        if not self._clipboard or not self._clipboard_op:
            self._toast("Clipboard is empty")
            return

        # Resolve paste destination:
        #   - as_child=True with cursor on todo: paste under that todo.
        #   - as_child=False with cursor on todo: paste as sibling.
        #   - no cursor: paste at top of current workspace.
        if cursor_todo:
            if as_child:
                parent_ws = None
                parent_td = cursor_todo["id"]
            else:
                parent_ws = cursor_todo.get("parent_workspace_id")
                parent_td = cursor_todo.get("parent_todo_id")
        else:
            if self.current_workspace_id is None:
                self._toast("No workspace selected")
                return
            parent_ws = self.current_workspace_id
            parent_td = None

        # For cut, refuse to paste into the cut todo's own subtree (cycle).
        clip = self._clipboard
        if self._clipboard_op == "cut" and parent_td is not None:
            if self._is_descendant_of(parent_td, clip):
                self._toast("Can't paste a todo into its own subtree")
                return

        try:
            await self._recreate_subtree(
                clip, parent_workspace_id=parent_ws, parent_todo_id=parent_td
            )
            if self._clipboard_op == "cut":
                await self.client.delete_todo(clip["id"])
        except KotoApiError as e:
            self._toast(f"Paste failed: {e.detail}")
            return

        # Successful paste: clear clipboard for cut, keep for copy.
        if self._clipboard_op == "cut":
            self._clipboard = None
            self._clipboard_op = None
            self.clipboard_cut_id = None
        await self._refresh()

    async def _recreate_subtree(
        self,
        src: dict,
        *,
        parent_workspace_id: Optional[int],
        parent_todo_id: Optional[int],
    ) -> None:
        """Re-create `src` (and its descendants) under the given parent."""
        new = await self.client.create_todo(
            src.get("description") or "",
            parent_workspace_id=parent_workspace_id,
            parent_todo_id=parent_todo_id,
        )
        # Apply the rest of the fields if any are non-default.
        patch: dict = {}
        if src.get("due"):
            patch["due"] = src["due"]
        if src.get("urgency", 1) != 1:
            patch["urgency"] = src["urgency"]
        if src.get("effort", 0):
            patch["effort"] = src["effort"]
        if src.get("recurrence_seconds"):
            patch["recurrence_seconds"] = src["recurrence_seconds"]
        if not src.get("pending", True):
            patch["pending"] = False
        if patch:
            await self.client.update_todo(new["id"], patch)

        for child in src.get("todos") or []:
            await self._recreate_subtree(
                child, parent_workspace_id=None, parent_todo_id=new["id"]
            )

    def _is_descendant_of(self, todo_id: int, root: dict) -> bool:
        """Return True if `todo_id` is `root` itself or any descendant of `root`."""
        if root.get("id") == todo_id:
            return True
        for child in root.get("todos") or []:
            if self._is_descendant_of(todo_id, child):
                return True
        return False

    async def _call(self, fn) -> None:
        """Wrap a client call: on success refresh; on error toast."""
        try:
            await fn()
        except KotoApiError as e:
            self._toast(f"Error: {e.detail}")
            return
        await self._refresh()

    # ---------- selection tracking ----------

    def on_tree_node_highlighted(self, event) -> None:
        """Persist the cursor across refreshes."""
        node = event.node
        if not node.data:
            return
        if isinstance(event.control, TodoTree):
            self.selected_todo_id = node.data.get("id")
        elif isinstance(event.control, WorkspaceTree):
            # We don't auto-load todos on highlight (only on Enter), but track
            # the cursor so workspace highlight persists.
            pass

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Mouse click (or Enter via Tree's default) on a workspace opens it."""
        node = event.node
        if not node.data:
            return
        if isinstance(event.control, WorkspaceTree):
            ws_id = node.data.get("id")
            if ws_id is None or ws_id == self.current_workspace_id:
                return
            self.current_workspace_id = ws_id
            self.selected_todo_id = None
            self.run_worker(self._refresh(), exclusive=True, group="ws_op:open")

    # ---------- WebSocket worker ----------

    def _start_ws_worker(self) -> None:
        self.run_worker(
            self._ws_loop(), exclusive=True, group="ws", name="ws"
        )

    async def _ws_loop(self) -> None:
        def _on_connect():
            self.ws_connected = True

        def _on_disconnect():
            self.ws_connected = False

        try:
            async for _ in self.client.watch_refresh(
                on_connect=_on_connect, on_disconnect=_on_disconnect
            ):
                # Schedule refresh on the app's loop (we're already on it,
                # but call_later avoids re-entrance during yield).
                self.call_later(self._refresh)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover - defensive
            self._toast(f"WS error: {e}")
