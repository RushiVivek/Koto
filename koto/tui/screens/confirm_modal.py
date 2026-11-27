"""Yes/no confirmation modal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static


class ConfirmModal(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("y", "confirm", "Yes"),
        Binding("n", "cancel", "No"),
        Binding("left", "app.focus_previous", "Previous", show=False),
        Binding("right", "app.focus_next", "Next", show=False),
    ]

    def __init__(self, message: str, *, title: str = "Confirm",
                 detail: str = "", confirm_label: str = "Yes"):
        super().__init__()
        self._message = message
        self._title = title
        self._detail = detail
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="dialog")
        dialog.border_title = self._title
        with dialog:
            # markup=False: user text may contain "[...]".
            yield Static(self._message, id="message", markup=False)
            if self._detail:
                yield Static(self._detail, id="detail", markup=False)
            with Horizontal(id="buttons"):
                yield Static("y / n", id="hint")
                yield Button("Cancel", id="no")
                yield Button(self._confirm_label, variant="error", id="yes")

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)
