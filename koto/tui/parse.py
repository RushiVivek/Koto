"""Pure parsers and formatters for the TUI: durations and due dates.

Kept independent of Textual so they're trivially unit-testable.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Optional


_DUR_PART = re.compile(r"(\d+)\s*([wdhms])", re.IGNORECASE)
_DUR_UNITS = {
    "w": 7 * 24 * 3600,
    "d": 24 * 3600,
    "h": 3600,
    "m": 60,
    "s": 1,
}


def parse_duration(text: str) -> Optional[int]:
    """Parse '1d', '3d', '2w', '12h', '90m', '1w 2d' → seconds. Empty → None."""
    s = text.strip().lower()
    if not s:
        return None
    parts = _DUR_PART.findall(s)
    if not parts:
        raise ValueError(f"Invalid duration: {text!r}")
    # Reject if there are non-matching characters left over.
    consumed = "".join(f"{n}{u}" for n, u in parts)
    stripped = re.sub(r"\s+", "", s)
    if consumed != stripped:
        raise ValueError(f"Invalid duration: {text!r}")
    total = 0
    for n, unit in parts:
        total += int(n) * _DUR_UNITS[unit.lower()]
    if total <= 0:
        raise ValueError(f"Duration must be > 0: {text!r}")
    return total


def format_duration(seconds: int) -> str:
    """Format seconds back to short form. 86400 → '1d'. 90000 → '1d 1h'."""
    if seconds <= 0:
        return ""
    parts: list[str] = []
    for unit, size in (("w", 7 * 24 * 3600), ("d", 24 * 3600),
                       ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= size:
            n, seconds = divmod(seconds, size)
            parts.append(f"{n}{unit}")
    return " ".join(parts)


_ISO_DATE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{1,2}))?$")
_REL_DAYS = re.compile(r"^\+(\d+)d$", re.IGNORECASE)


def parse_due(text: str, now: Optional[datetime] = None) -> Optional[datetime]:
    """Parse 'today', 'tomorrow', '+3d', '2026-06-15', '2026-06-15 14:30' → datetime.

    Empty → None.
    """
    s = text.strip().lower()
    if not s:
        return None
    now = now or datetime.now()
    if s == "today":
        return now.replace(hour=23, minute=59, second=0, microsecond=0)
    if s == "tomorrow":
        d = now + timedelta(days=1)
        return d.replace(hour=23, minute=59, second=0, microsecond=0)
    m = _REL_DAYS.match(s)
    if m:
        d = now + timedelta(days=int(m.group(1)))
        return d.replace(hour=23, minute=59, second=0, microsecond=0)
    m = _ISO_DATE.match(text.strip())
    if m:
        year, mon, day, hh, mm = m.groups()
        return datetime(
            int(year), int(mon), int(day),
            int(hh) if hh else 0,
            int(mm) if mm else 0,
        )
    raise ValueError(f"Invalid date: {text!r}")


def format_due(d: datetime, now: Optional[datetime] = None) -> str:
    """Friendly format: 'Today', 'Tomorrow', 'Mon', 'Jan 5', 'Jan 5 2027'."""
    now = now or datetime.now()
    today = now.date()
    target = d.date()
    if target == today:
        return "Today"
    if target == today + timedelta(days=1):
        return "Tomorrow"
    delta = (target - today).days
    if 0 < delta < 7:
        return d.strftime("%a")
    if d.year == now.year:
        return d.strftime("%b %-d")
    return d.strftime("%b %-d %Y")


def format_due_iso_input(d: Optional[datetime]) -> str:
    """ISO-ish form for prefilling the edit modal Input."""
    if d is None:
        return ""
    if d.hour == 0 and d.minute == 0:
        return d.strftime("%Y-%m-%d")
    return d.strftime("%Y-%m-%d %H:%M")
