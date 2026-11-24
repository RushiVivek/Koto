"""Local, per-machine TUI state (e.g. which tree nodes are folded).

Stored as JSON next to other platform state; never sent to the server.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


class UiState:
    """Collapsed-node ids per tree, optionally persisted to `path`.

    With `path=None` the state lives only in memory (used by tests).
    """

    def __init__(self, path: Optional[Path] = None):
        self.path = path
        self._collapsed: dict[str, set[int]] = {}
        if path is not None:
            self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text())
            collapsed = raw.get("collapsed", {})
            self._collapsed = {
                key: {int(i) for i in ids} for key, ids in collapsed.items()
            }
        except (OSError, ValueError, TypeError, AttributeError):
            # Missing or corrupt file: start fresh rather than crash the TUI.
            self._collapsed = {}

    def collapsed(self, key: str) -> set[int]:
        """The live, mutable set of collapsed ids for tree `key`."""
        return self._collapsed.setdefault(key, set())

    def save(self) -> None:
        if self.path is None:
            return
        data = {"collapsed": {k: sorted(v) for k, v in self._collapsed.items()}}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, self.path)
        except OSError:
            # Read-only filesystem etc. — folding still works for this session.
            pass
