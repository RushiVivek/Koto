"""WorkspaceTree: shows the nested workspace tree with status badges."""

from __future__ import annotations

from typing import Any, Optional

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ...schemas import UNTITLED


class WorkspaceTree(Tree):
    """Tree of workspaces. Each node's `data` is the WorkspaceOut dict."""

    ALLOW_MAXIMIZE = False

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

    def __init__(self, **kwargs):
        super().__init__("Workspaces", **kwargs)
        self.show_root = False
        self.show_guides = True
        self.guide_depth = 2
        # Don't toggle expansion when the user (or `select_id`) selects a
        # node — only the explicit `o` binding should do that.
        self.auto_expand = False
        # Set of workspace ids the user has explicitly collapsed. Anything
        # not in here is shown expanded by default. Persists across populate().
        self._collapsed_ids: set[int] = set()
        # Guard: clear()/add() during populate() fires Collapsed/Expanded
        # events that aren't user-initiated. Ignore them.
        self._populating = False

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

    # ---------- population ----------

    def populate(self, workspaces: list[dict]) -> None:
        """Rebuild the tree from a workspace list, preserving expansion state.

        If the structure (ids/order/parents) hasn't changed, only refresh
        each node's data in place — avoids the cursor jump on a refresh
        that's just badge-count updates.
        """
        if self._structure_matches(workspaces):
            self._refresh_data(self.root, workspaces)
            return
        self._populating = True
        try:
            self.clear()
            for ws in workspaces:
                self._add_workspace(self.root, ws)
        finally:
            self._populating = False
        if self.root.children:
            self.select_node(self.root.children[0])

    def _structure_matches(self, workspaces: list[dict]) -> bool:
        def walk(nodes, items):
            if len(nodes) != len(items):
                return False
            for n, item in zip(nodes, items):
                if not n.data or n.data.get("id") != item["id"]:
                    return False
                if not walk(n.children, item.get("workspaces") or []):
                    return False
            return True
        return walk(self.root.children, workspaces)

    def _refresh_data(self, node: TreeNode, items: list[dict]) -> None:
        for child_node, item in zip(node.children, items):
            child_node.data = item
            self._refresh_data(child_node, item.get("workspaces") or [])
        # Tree caches rendered lines; clear so updated data shows immediately.
        self._invalidate()

    def _add_workspace(self, parent_node: TreeNode, ws: dict) -> TreeNode:
        expanded = ws["id"] not in self._collapsed_ids
        node = parent_node.add(
            ws.get("description") or UNTITLED, data=ws, expand=expanded
        )
        for child in ws.get("workspaces", []):
            self._add_workspace(node, child)
        return node

    def on_tree_node_collapsed(self, event) -> None:
        if self._populating:
            return
        ws = event.node.data
        if ws:
            self._collapsed_ids.add(ws["id"])

    def on_tree_node_expanded(self, event) -> None:
        if self._populating:
            return
        ws = event.node.data
        if ws:
            self._collapsed_ids.discard(ws["id"])

    def find_node(self, ws_id: int) -> Optional[TreeNode]:
        """Walk the tree and return the node matching the given workspace id."""
        def walk(n: TreeNode):
            for child in n.children:
                if child.data and child.data.get("id") == ws_id:
                    return child
                found = walk(child)
                if found:
                    return found
            return None
        return walk(self.root)

    def select_id(self, ws_id: Optional[int]) -> None:
        if ws_id is None:
            return
        node = self.find_node(ws_id)
        if node is not None:
            self.select_node(node)

    @property
    def current(self) -> Optional[dict]:
        node = self.cursor_node
        return node.data if node else None

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

    def action_right_arrow(self) -> None:
        # If the workspace has sub-workspaces, jump to the first child
        # (expand if needed). Otherwise open it and focus the todo panel.
        node = self.cursor_node
        if node and node.children:
            if not node.is_expanded:
                node.expand()
            self.select_node(node.children[0])
        else:
            self._emit("open")

    def action_left_arrow(self) -> None:
        # Move cursor to the parent workspace, if any.
        node = self.cursor_node
        if node and node.parent and node.parent.data:
            self.select_node(node.parent)
