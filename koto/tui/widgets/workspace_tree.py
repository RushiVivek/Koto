"""WorkspaceTree: shows the nested workspace tree with status badges."""

from __future__ import annotations

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.widgets.tree import TreeNode

from ...schemas import UNTITLED
from .koto_tree import KotoTree


class WorkspaceTree(KotoTree):
    """Tree of workspaces. Each node's `data` is the WorkspaceOut dict."""

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("o", "toggle_node", "Expand/collapse", show=False),
        Binding("enter", "open_workspace", "Open", show=True),
        Binding("n", "new_workspace", "New", show=True),
        Binding("N", "new_subworkspace", "Sub", show=False),
        Binding("e", "edit_workspace", "Rename", show=False),
        Binding("d", "delete_workspace", "Delete", show=False),
        Binding("shift+down", "reorder_down", "Move ↓", show=False),
        Binding("shift+up", "reorder_up", "Move ↑", show=False),
        Binding("space", "open_workspace", "Open", show=False),
        Binding("right", "right_arrow", "Open workspace", show=False),
        Binding("left", "left_arrow", "Parent", show=False),
    ]

    CHILDREN_KEY = "workspaces"

    def __init__(self, **kwargs):
        super().__init__("Workspaces", **kwargs)

    # ---------- rendering ----------

    def render_label(
        self, node: TreeNode, base_style: Style, style: Style
    ) -> Text:
        ws = node.data
        if not ws:
            label = node.label
            return label if isinstance(label, Text) else Text(str(label), style=style)

        has_children = bool(ws.get("workspaces"))
        if has_children:
            icon = "▾" if node.is_expanded else "▸"
        else:
            icon = "·"
        text = Text(style=style)
        text.append(f"{icon} ", style="dim")
        text.append(ws.get("description") or UNTITLED)

        # Inline badges
        badges = self._badges(ws)
        if badges:
            text.append("  ")
            text.append_text(badges)
        return text

    def _badges(self, ws: dict) -> Text:
        total = ws.get("todo_count", 0)
        if total == 0:
            return Text()
        out = Text()
        overdue = ws.get("overdue_count", 0)
        today = ws.get("due_today_count", 0)
        pending = ws.get("pending_count", 0)
        done = ws.get("done_count", 0)

        if overdue > 0:
            out.append(f"!{overdue} ", style="bold red")
        if today > 0:
            out.append(f"{today}d ", style="yellow")
        if pending == 0:
            out.append(f"✓ {total}", style="green")
        else:
            out.append(f"{done}/{total}", style="dim")
        return out

    # ---------- actions (delegate to app) ----------

    def _emit(self, action: str) -> None:
        # exclusive=True per-action-group: rapid-fire of the same key (e.g.
        # double `space` toggle) cancels the in-flight one. Different ops
        # (e.g. `n` while `d` confirm is open) don't block each other.
        self.app.run_worker(  # type: ignore[attr-defined]
            self.app.action_workspace_op(action),  # type: ignore[attr-defined]
            exclusive=True,
            group=f"ws_op:{action}",
        )

    def action_new_workspace(self) -> None:
        self._emit("new")

    def action_new_subworkspace(self) -> None:
        self._emit("new_sub")

    def action_edit_workspace(self) -> None:
        self._emit("edit")

    def action_delete_workspace(self) -> None:
        self._emit("delete")

    def action_reorder_down(self) -> None:
        self._emit("reorder_down")

    def action_reorder_up(self) -> None:
        self._emit("reorder_up")

    def action_open_workspace(self) -> None:
        self._emit("open")

    def on_right_at_leaf(self) -> None:
        # No sub-workspaces: open it and focus the todo panel.
        self._emit("open")
