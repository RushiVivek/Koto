"""TodoTree: shows todos for a workspace, with sub-todos as nested nodes."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ...schemas import UNTITLED
from ..parse import format_due, format_duration


class TodoTree(Tree):
    """Tree of todos. Each node's `data` is the TodoOut dict."""

    ALLOW_MAXIMIZE = False

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),
        Binding("o", "toggle_node", "Expand/collapse", show=False),
        Binding("space", "toggle_todo", "Toggle", show=True),
        Binding("n", "new_todo", "New", show=True),
        Binding("N", "new_subtodo", "Sub", show=False),
        Binding("e", "edit_todo", "Edit", show=True),
        Binding("d", "delete_todo", "Delete", show=False),
        Binding("x", "cut_todo", "Cut", show=False),
        Binding("c", "copy_todo", "Copy", show=False),
        Binding("p", "paste_todo", "Paste", show=False),
        Binding("P", "paste_todo_child", "Paste as child", show=False),
        Binding("shift+down", "reorder_down", "Move ↓", show=False),
        Binding("shift+up", "reorder_up", "Move ↑", show=False),
        Binding("s", "sort_completed", "Sort done last", show=False),
        Binding("left", "left_arrow", "Parent / Workspaces", show=False),
        Binding("right", "right_arrow", "First child", show=False),
        Binding("escape", "focus_workspaces", "Workspaces", show=False),
    ]

    def __init__(self, **kwargs):
        super().__init__("Todos", **kwargs)
        self.show_root = False
        self.show_guides = True
        self.guide_depth = 2
        self.auto_expand = False
        # Same expansion-state persistence as WorkspaceTree.
        self._collapsed_ids: set[int] = set()
        self._populating = False
        # Cut-styling: id of the todo currently in "cut" clipboard, or None.
        # Set by the app via `set_cut_id` so render_label can stay sync.
        self._cut_id: Optional[int] = None

    # ---------- rendering ----------

    # Column widths for the right-aligned meta strip.
    # Order: due | urgency | effort | recurrence | sub-progress
    COL_DUE = 12
    COL_URG = 5
    COL_EFFORT = 5
    COL_RECUR = 11  # ↻3d·999
    COL_PROGRESS = 7
    COL_GAP = 2  # spaces between columns
    DESC_GAP = 4  # spaces between description and the meta strip

    @property
    def _meta_strip_width(self) -> int:
        return (
            self.COL_DUE + self.COL_URG + self.COL_EFFORT
            + self.COL_RECUR + self.COL_PROGRESS
            + self.COL_GAP * 4
        )

    def render_label(
        self, node: TreeNode, base_style: Style, style: Style
    ) -> Text:
        todo = node.data
        if not todo:
            label = node.label
            return label if isinstance(label, Text) else Text(str(label), style=style)

        text = Text(style=style)
        if self._is_cut(todo):
            text.append("✂ ", style="dim italic")
        text.append("☐ " if todo.get("pending") else "☑ ",
                    style=None if todo.get("pending") else "green")

        # Compute room available for the description so the meta columns
        # always start at the same x-position.
        # `self.size.width` is the rendered width; subtract guides + checkbox
        # + cut-marker + gap + meta strip.
        depth = self._node_depth(node)
        guide_width = max(0, depth - 1) * self.guide_depth
        prefix_width = (
            (2 if self._is_cut(todo) else 0)  # "✂ "
            + 2  # checkbox glyph + space
        )
        avail = (
            self.size.width - guide_width - prefix_width
            - self.DESC_GAP - self._meta_strip_width
        )
        desc = todo.get("description") or UNTITLED
        if avail > 0 and len(desc) > avail:
            desc = desc[: max(1, avail - 1)] + "…"
        actual_desc_cells = len(desc)

        if not todo.get("pending"):
            text.append(desc, style="strike dim")
        else:
            text.append(desc)

        # Pad to fill the description column so meta starts at a consistent x.
        # If avail is unknown (size not yet set) just use a short gap.
        target_desc_cells = max(actual_desc_cells, avail) if avail > 0 else actual_desc_cells
        pad_to_meta = target_desc_cells - actual_desc_cells + self.DESC_GAP
        if pad_to_meta > 0:
            text.append(" " * pad_to_meta)

        # Right-aligned columns separated by 2 spaces.
        gap = " " * self.COL_GAP
        text.append_text(self._col(self._due_text(todo), self.COL_DUE))
        text.append(gap)
        text.append_text(self._col(self._urgency_text(todo), self.COL_URG))
        text.append(gap)
        text.append_text(self._col(self._effort_text(todo), self.COL_EFFORT))
        text.append(gap)
        text.append_text(self._col(self._recur_text(todo), self.COL_RECUR))
        text.append(gap)
        text.append_text(self._col(self._progress_text(todo), self.COL_PROGRESS))

        return text

    @staticmethod
    def _node_depth(node: TreeNode) -> int:
        d = 0
        n = node
        while n.parent is not None:
            d += 1
            n = n.parent
        return d

    @staticmethod
    def _col(value: Text, width: int) -> Text:
        # Right-align by left-padding with spaces.
        pad = max(0, width - value.cell_len)
        if pad:
            return Text(" " * pad) + value
        return value

    @staticmethod
    def _due_text(todo: dict) -> Text:
        due_iso = todo.get("due")
        if not due_iso:
            return Text("")
        try:
            d = datetime.fromisoformat(due_iso)
        except (ValueError, TypeError):
            return Text("")
        overdue = todo.get("pending") and d < datetime.now()
        return Text(format_due(d), style="bold red" if overdue else "yellow")

    @staticmethod
    def _urgency_text(todo: dict) -> Text:
        u = todo.get("urgency", 1)
        if u <= 1:
            return Text("")
        return Text("!" * min(u, 4), style="bold magenta")

    @staticmethod
    def _effort_text(todo: dict) -> Text:
        e = todo.get("effort", 0)
        if not e:
            return Text("")
        return Text(f"e{e}", style="blue")

    @staticmethod
    def _recur_text(todo: dict) -> Text:
        r = todo.get("recurrence_seconds")
        if not r:
            return Text("")
        count = todo.get("recurrence_count", 0)
        label = f"↻{format_duration(r)}"
        if count:
            label += f"·{count}"
        return Text(label, style="cyan")

    @staticmethod
    def _progress_text(todo: dict) -> Text:
        children = todo.get("todos") or []
        if not children:
            return Text("")
        done = sum(1 for c in children if not c.get("pending"))
        return Text(f"{done}/{len(children)}", style="dim")

    def set_cut_id(self, cut_id: Optional[int]) -> None:
        self._cut_id = cut_id
        self._invalidate()

    def _is_cut(self, todo: dict) -> bool:
        return self._cut_id is not None and todo.get("id") == self._cut_id

    # ---------- population ----------

    def populate(self, todos: list[dict]) -> None:
        if self._structure_matches(todos):
            self._refresh_data(self.root, todos)
            return
        self._populating = True
        try:
            self.clear()
            for todo in todos:
                self._add_todo(self.root, todo)
        finally:
            self._populating = False
        # Place cursor on first node so that key actions have a target.
        if self.root.children:
            self.select_node(self.root.children[0])

    def _structure_matches(self, todos: list[dict]) -> bool:
        def walk(nodes, items):
            if len(nodes) != len(items):
                return False
            for n, item in zip(nodes, items):
                if not n.data or n.data.get("id") != item["id"]:
                    return False
                if not walk(n.children, item.get("todos") or []):
                    return False
            return True
        return walk(self.root.children, todos)

    def _refresh_data(self, node: TreeNode, items: list[dict]) -> None:
        for child_node, item in zip(node.children, items):
            child_node.data = item
            self._refresh_data(child_node, item.get("todos") or [])
        self._invalidate()

    def _add_todo(self, parent_node: TreeNode, todo: dict) -> TreeNode:
        expanded = todo["id"] not in self._collapsed_ids
        node = parent_node.add(
            todo.get("description") or UNTITLED, data=todo, expand=expanded
        )
        for child in todo.get("todos") or []:
            self._add_todo(node, child)
        return node

    def on_tree_node_collapsed(self, event) -> None:
        if self._populating:
            return
        todo = event.node.data
        if todo:
            self._collapsed_ids.add(todo["id"])

    def on_tree_node_expanded(self, event) -> None:
        if self._populating:
            return
        todo = event.node.data
        if todo:
            self._collapsed_ids.discard(todo["id"])

    def find_node(self, todo_id: int) -> Optional[TreeNode]:
        def walk(n: TreeNode):
            for child in n.children:
                if child.data and child.data.get("id") == todo_id:
                    return child
                found = walk(child)
                if found:
                    return found
            return None
        return walk(self.root)

    def select_id(self, todo_id: Optional[int]) -> None:
        if todo_id is None:
            return
        node = self.find_node(todo_id)
        if node is not None:
            self.select_node(node)

    @property
    def current(self) -> Optional[dict]:
        node = self.cursor_node
        return node.data if node else None

    # ---------- actions ----------

    def _emit(self, action: str) -> None:
        # exclusive=True per-action-group: rapid-fire of the same key
        # cancels the in-flight one. Different ops don't block each other.
        self.app.run_worker(  # type: ignore[attr-defined]
            self.app.action_todo_op(action),  # type: ignore[attr-defined]
            exclusive=True,
            group=f"todo_op:{action}",
        )

    def action_toggle_todo(self) -> None:
        self._emit("toggle")

    def action_new_todo(self) -> None:
        self._emit("new")

    def action_new_subtodo(self) -> None:
        self._emit("new_sub")

    def action_edit_todo(self) -> None:
        self._emit("edit")

    def action_delete_todo(self) -> None:
        self._emit("delete")

    def action_cut_todo(self) -> None:
        self._emit("cut")

    def action_copy_todo(self) -> None:
        self._emit("copy")

    def action_paste_todo(self) -> None:
        self._emit("paste")

    def action_paste_todo_child(self) -> None:
        self._emit("paste_child")

    def action_sort_completed(self) -> None:
        self._emit("sort_completed")

    def action_reorder_down(self) -> None:
        self._emit("reorder_down")

    def action_reorder_up(self) -> None:
        self._emit("reorder_up")

    def action_left_arrow(self) -> None:
        # If cursor is on a sub-todo, jump to its parent. Otherwise focus
        # the workspace panel.
        node = self.cursor_node
        if node and node.parent and node.parent.data:
            self.select_node(node.parent)
        else:
            self.app.action_focus_workspaces()  # type: ignore[attr-defined]

    def action_focus_workspaces(self) -> None:
        self.app.action_focus_workspaces()  # type: ignore[attr-defined]

    def action_right_arrow(self) -> None:
        # If cursor has children, jump to the first one (expand if needed).
        # Otherwise no-op.
        node = self.cursor_node
        if not node:
            return
        if node.children:
            if not node.is_expanded:
                node.expand()
            self.select_node(node.children[0])
