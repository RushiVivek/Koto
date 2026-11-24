"""KotoTree: shared base for the workspace and todo trees.

Each node's `data` is a server dict with an `id` and a list of children
under `CHILDREN_KEY`. Handles rebuild-vs-refresh, persisted fold state,
and cursor placement.
"""

from __future__ import annotations

from typing import Optional

from textual.widgets import Tree
from textual.widgets.tree import TreeNode

from ...schemas import UNTITLED
from ..state import UiState


class KotoTree(Tree):
    ALLOW_MAXIMIZE = False

    # Key of the child list in each item dict; also the UiState key.
    CHILDREN_KEY: str = ""

    def __init__(self, label: str, *, state: Optional[UiState] = None, **kwargs):
        super().__init__(label, **kwargs)
        self.show_root = False
        self.show_guides = True
        self.guide_depth = 2
        # Don't toggle expansion when a node is selected — only the explicit
        # `o` binding should do that.
        self.auto_expand = False
        self._state = state or UiState()
        # Ids the user has collapsed. Anything not in here is expanded.
        self._collapsed_ids = self._state.collapsed(self.CHILDREN_KEY)
        # Guard: clear()/add() during populate() aren't user fold actions.
        self._populating = False

    # ---------- population ----------

    def populate(self, items: list[dict]) -> None:
        """Rebuild the tree from `items`, preserving fold state.

        If the structure (ids/order/nesting) is unchanged, only refresh each
        node's data in place — avoids a cursor jump on a counts-only refresh.
        """
        if self._structure_matches(items):
            self._refresh_data(self.root, items)
            return
        self._populating = True
        try:
            self.clear()
            for item in items:
                self._add_item(self.root, item)
        finally:
            self._populating = False
        # Give key actions a target; callers re-place it via `select_id`.
        if self.root.children:
            self.move_to(self.root.children[0])

    def _children(self, item: dict) -> list[dict]:
        return item.get(self.CHILDREN_KEY) or []

    def _structure_matches(self, items: list[dict]) -> bool:
        def walk(nodes, items):
            if len(nodes) != len(items):
                return False
            for n, item in zip(nodes, items):
                if not n.data or n.data.get("id") != item["id"]:
                    return False
                if not walk(n.children, self._children(item)):
                    return False
            return True
        return walk(self.root.children, items)

    def _refresh_data(self, node: TreeNode, items: list[dict]) -> None:
        for child_node, item in zip(node.children, items):
            child_node.data = item
            self._refresh_data(child_node, self._children(item))
        # Tree caches rendered lines; clear so updated data shows immediately.
        self._invalidate()

    def _add_item(self, parent_node: TreeNode, item: dict) -> TreeNode:
        node = parent_node.add(
            item.get("description") or UNTITLED,
            data=item,
            expand=item["id"] not in self._collapsed_ids,
        )
        for child in self._children(item):
            self._add_item(node, child)
        return node

    # ---------- fold persistence ----------

    def _set_collapsed(self, node: TreeNode, collapsed: bool) -> None:
        if self._populating or not node.data:
            return
        item_id = node.data["id"]
        if collapsed == (item_id in self._collapsed_ids):
            return
        if collapsed:
            self._collapsed_ids.add(item_id)
        else:
            self._collapsed_ids.discard(item_id)
        self._state.save()

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        self._set_collapsed(event.node, True)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        self._set_collapsed(event.node, False)

    # ---------- cursor ----------

    def move_to(self, node: TreeNode) -> None:
        """Move the cursor without posting NodeSelected.

        `select_node` posts NodeSelected, which the app treats as "open this
        workspace" — programmatic cursor moves must not do that.
        """
        # Freshly added nodes have no line number until the tree is rebuilt.
        self._tree_lines  # noqa: B018 — property access forces the rebuild
        self.move_cursor(node)

    def find_node(self, item_id: int) -> Optional[TreeNode]:
        def walk(n: TreeNode):
            for child in n.children:
                if child.data and child.data.get("id") == item_id:
                    return child
                found = walk(child)
                if found:
                    return found
            return None
        return walk(self.root)

    def select_id(self, item_id: Optional[int]) -> None:
        if item_id is None:
            return
        node = self.find_node(item_id)
        if node is not None:
            self.move_to(node)

    @property
    def current(self) -> Optional[dict]:
        node = self.cursor_node
        return node.data if node else None

    def action_left_arrow(self) -> None:
        """Move to the parent node; subclasses decide what happens at the top."""
        node = self.cursor_node
        if node and node.parent and node.parent.data:
            self.move_to(node.parent)
        else:
            self.on_left_at_top()

    def on_left_at_top(self) -> None:
        pass

    def action_right_arrow(self) -> None:
        """Move to the first child (expanding if needed), else `on_right_at_leaf`."""
        node = self.cursor_node
        if not node:
            return
        if node.children:
            if not node.is_expanded:
                node.expand()
            self.move_to(node.children[0])
        else:
            self.on_right_at_leaf()

    def on_right_at_leaf(self) -> None:
        pass
