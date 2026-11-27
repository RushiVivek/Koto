"""Single-line input modal."""

from __future__ import annotations

from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Static


class InputModal(ModalScreen[Optional[str]]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        # The Input consumes left/right for its text cursor, so these only
        # fire with a button focused.
        Binding("down", "focus_button", show=False),
        Binding("up", "focus_input", show=False),
        Binding("left", "switch_button", show=False),
        Binding("right", "switch_button", show=False),
    ]

    def __init__(self, title: str, initial: str = "", placeholder: str = ""):
        super().__init__()
        self._title = title
        self._initial = initial
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        dialog = Vertical(id="dialog")
        dialog.border_title = self._title
        with dialog:
            yield Input(value=self._initial, placeholder=self._placeholder, id="input")
            with Horizontal(id="buttons"):
                yield Static("enter / esc", id="hint")
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._save()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def _save(self) -> None:
        val = self.query_one("#input", Input).value.strip()
        if not val:
            self.dismiss(None)
        else:
            self.dismiss(val)

    def action_focus_button(self) -> None:
        if isinstance(self.focused, Input):
            self.query_one("#save", Button).focus()

    def action_focus_input(self) -> None:
        self.query_one("#input", Input).focus()

    def action_switch_button(self) -> None:
        if isinstance(self.focused, Button):
            other = "#cancel" if self.focused.id == "save" else "#save"
            self.query_one(other, Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
