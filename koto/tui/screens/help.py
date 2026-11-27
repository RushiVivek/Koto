"""Help screen showing keybindings."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


HELP_TEXT = """\
[b]Global[/b]
  ?           Show this help
  q           Quit
  r           Force refresh
  1, 2        Focus workspaces / todos panel

[b]Workspace tree[/b]
  ↑ / ↓       Move up / down
  →           First sub-workspace, or open todos if none
  ←           Move to parent workspace
  o           Toggle expand / collapse cursor
  enter,space Open workspace (also: mouse click)
  n           New workspace (sibling of cursor)
  N           New sub-workspace under cursor
  e           Rename workspace
  d           Delete workspace
  shift+↓/↑   Reorder down / up

[b]Todo tree[/b]
  ↑ / ↓       Move up / down
  →           First sub-todo (expands if needed)
  ←           Move to parent todo, or back to workspaces if at root
  escape      Switch to workspaces panel
  o           Toggle expand / collapse cursor
  space       Toggle pending
  n           New todo (sibling of cursor)
  N           New sub-todo under cursor
  e           Edit (description, due, urgency, effort, recurrence)
  d           Delete todo
  x, c, p     Cut / Copy / Paste todo (as sibling, with subtree)
  P           Paste as child of cursor
  shift+↓/↑   Reorder down / up
  s           Sort: completed siblings to bottom

[b]Todo columns[/b]
  Right-aligned: Due  Urgency(!)  Effort(eN)  Recurrence(↻)  Sub-progress

[b]Modals[/b]
  escape      Cancel
  enter       Save (in single-input modals)
  tab/shift-tab  Field navigation (in edit modal)

[b]Recurrence[/b]
  Toggling a recurring todo advances its due date by the recurrence interval
  instead of marking it complete. Same when its last child completes (unless
  no due date is set, in which case due stays empty).
"""


class HelpScreen(ModalScreen[None]):
    BINDINGS = [Binding("escape,q,?", "close", "Close")]

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="dialog")
        dialog.border_title = "Help"
        with dialog:
            yield Static(HELP_TEXT, id="help")
            with Horizontal(id="buttons"):
                yield Button("Close", id="close")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(None)

    def action_close(self) -> None:
        self.dismiss(None)
