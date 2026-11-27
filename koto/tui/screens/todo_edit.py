"""TodoEditModal: full-field todo editor (description, due, urgency, effort, recurrence)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static

from ..parse import (
    format_due_iso_input,
    format_duration,
    parse_due,
    parse_duration,
)


class TodoEditModal(ModalScreen[Optional[dict]]):
    """Edit a todo's fields. Returns a dict of only-changed fields, or None on cancel.

    Field semantics:
      - description: empty -> not changed (you can't blank-out a todo description)
      - due: empty -> null (clear); otherwise parsed
      - urgency: empty -> not changed; numeric 0..10
      - effort: empty -> not changed; numeric 0..100
      - recurrence: empty -> null (clear); short form parsed via parse_duration
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("down", "move(1)", show=False),
        Binding("up", "move(-1)", show=False),
        # Inputs consume left/right for their text cursor, so these only
        # fire with a button focused.
        Binding("left", "switch_button", show=False),
        Binding("right", "switch_button", show=False),
    ]

    FIELDS = ("#desc", "#due", "#urgency", "#effort", "#recurrence")

    def __init__(self, todo: dict):
        super().__init__()
        self._todo = todo

    def compose(self) -> ComposeResult:
        t = self._todo
        due_init = ""
        if t.get("due"):
            try:
                due_init = format_due_iso_input(datetime.fromisoformat(t["due"]))
            except Exception:
                due_init = t["due"]

        recur_init = (
            format_duration(t["recurrence_seconds"])
            if t.get("recurrence_seconds")
            else ""
        )

        dialog = Vertical(id="dialog")
        dialog.border_title = "Edit todo"
        with dialog:
            yield Label("Description", classes="first")
            yield Input(value=t.get("description") or "", id="desc")
            yield Label("Due (e.g. 2026-06-15, 2026-06-15 14:30, today, +3d, blank to clear)")
            yield Input(value=due_init, id="due")
            yield Label("Urgency (0-10)")
            yield Input(value=str(t.get("urgency", 1)), id="urgency")
            yield Label("Effort (0-100)")
            yield Input(value=str(t.get("effort", 0)), id="effort")
            yield Label("Recurrence (e.g. 1d, 3d, 2w, 12h, blank to clear)")
            yield Input(value=recur_init, id="recurrence")
            yield Static("", id="error")
            with Horizontal(id="buttons"):
                yield Static("esc", id="hint")
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    def on_mount(self) -> None:
        self.query_one("#desc", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            self._save()
        else:
            self.dismiss(None)

    def action_move(self, step: int) -> None:
        """Up/down through the fields; past the last field lands on Save."""
        focused = self.focused
        if isinstance(focused, Button):
            if step < 0:
                self.query_one(self.FIELDS[-1], Input).focus()
            return
        ids = [f.lstrip("#") for f in self.FIELDS]
        if focused is None or focused.id not in ids:
            return
        i = ids.index(focused.id) + step
        if i >= len(ids):
            self.query_one("#save", Button).focus()
        elif i >= 0:
            self.query_one(self.FIELDS[i], Input).focus()

    def action_switch_button(self) -> None:
        if isinstance(self.focused, Button):
            other = "#cancel" if self.focused.id == "save" else "#save"
            self.query_one(other, Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def _set_error(self, msg: str) -> None:
        err = self.query_one("#error", Static)
        err.update(msg)
        err.add_class("visible")

    def _save(self) -> None:
        t = self._todo
        new_desc = self.query_one("#desc", Input).value
        new_due_text = self.query_one("#due", Input).value.strip()
        new_urg_text = self.query_one("#urgency", Input).value.strip()
        new_eff_text = self.query_one("#effort", Input).value.strip()
        new_rec_text = self.query_one("#recurrence", Input).value.strip()

        changed: dict[str, Any] = {}

        # Description: only set if non-empty AND changed.
        if new_desc and new_desc != (t.get("description") or ""):
            changed["description"] = new_desc

        # Due: empty means clear (null); otherwise parse.
        try:
            new_due = parse_due(new_due_text) if new_due_text else None
        except ValueError as e:
            self._set_error(str(e))
            return
        # Compare datetimes, not strings, so a Pydantic serializer change
        # (microseconds, timezone) doesn't false-positive here.
        old_due = None
        old_due_iso = t.get("due")
        if old_due_iso:
            try:
                old_due = datetime.fromisoformat(old_due_iso)
            except ValueError:
                pass
        if new_due != old_due:
            changed["due"] = new_due.isoformat() if new_due else None

        # Urgency
        if new_urg_text:
            try:
                new_urg = int(new_urg_text)
                if not (0 <= new_urg <= 10):
                    raise ValueError("Urgency must be 0..10")
            except ValueError as e:
                self._set_error(f"Bad urgency: {e}")
                return
            if new_urg != t.get("urgency", 1):
                changed["urgency"] = new_urg

        # Effort
        if new_eff_text:
            try:
                new_eff = int(new_eff_text)
                if not (0 <= new_eff <= 100):
                    raise ValueError("Effort must be 0..100")
            except ValueError as e:
                self._set_error(f"Bad effort: {e}")
                return
            if new_eff != t.get("effort", 0):
                changed["effort"] = new_eff

        # Recurrence
        try:
            new_rec = parse_duration(new_rec_text) if new_rec_text else None
        except ValueError as e:
            self._set_error(f"Bad recurrence: {e}")
            return
        if new_rec != t.get("recurrence_seconds"):
            changed["recurrence_seconds"] = new_rec

        if not changed:
            self.dismiss(None)
            return
        self.dismiss(changed)
