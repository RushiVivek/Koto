"""Pure tests for koto.tui.parse — no Textual involved."""

from datetime import datetime, timedelta

import pytest

from koto.tui.parse import (
    format_due,
    format_due_iso_input,
    format_duration,
    parse_due,
    parse_duration,
)


# ---------------- parse_duration ----------------


@pytest.mark.parametrize(
    "text,seconds",
    [
        ("", None),
        ("1d", 86400),
        ("3d", 3 * 86400),
        ("2w", 14 * 86400),
        ("12h", 12 * 3600),
        ("90m", 90 * 60),
        ("30s", 30),
        ("1w 2d", 9 * 86400),
        ("1d 12h", 86400 + 12 * 3600),
        ("  2D  ", 2 * 86400),
    ],
)
def test_parse_duration_ok(text, seconds):
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text",
    ["abc", "1x", "0d", "-1d", "1.5d", "d", "1"],
)
def test_parse_duration_rejects(text):
    with pytest.raises(ValueError):
        parse_duration(text)


# ---------------- format_duration ----------------


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, ""),
        (-5, ""),
        (86400, "1d"),
        (3 * 86400, "3d"),
        (12 * 3600, "12h"),
        (90 * 60, "1h 30m"),
        (9 * 86400, "1w 2d"),
        (60, "1m"),
    ],
)
def test_format_duration(seconds, expected):
    assert format_duration(seconds) == expected


def test_duration_round_trip():
    for s in [60, 3600, 86400, 90 * 60, 2 * 7 * 86400]:
        assert parse_duration(format_duration(s)) == s


# ---------------- parse_due ----------------


def test_parse_due_empty():
    assert parse_due("") is None


def test_parse_due_today():
    now = datetime(2026, 5, 30, 14, 0)
    d = parse_due("today", now=now)
    assert d.date() == now.date()
    assert d.hour == 23 and d.minute == 59


def test_parse_due_tomorrow():
    now = datetime(2026, 5, 30, 14, 0)
    d = parse_due("tomorrow", now=now)
    assert d.date() == (now + timedelta(days=1)).date()


def test_parse_due_relative():
    now = datetime(2026, 5, 30, 14, 0)
    d = parse_due("+3d", now=now)
    assert d.date() == (now + timedelta(days=3)).date()


def test_parse_due_iso_date():
    d = parse_due("2026-06-15")
    assert d == datetime(2026, 6, 15, 0, 0)


def test_parse_due_iso_datetime():
    d = parse_due("2026-06-15 14:30")
    assert d == datetime(2026, 6, 15, 14, 30)


def test_parse_due_iso_T():
    d = parse_due("2026-06-15T14:30")
    assert d == datetime(2026, 6, 15, 14, 30)


def test_parse_due_invalid():
    with pytest.raises(ValueError):
        parse_due("not a date")


# ---------------- format_due ----------------


def test_format_due_today():
    now = datetime(2026, 5, 30, 14, 0)
    assert format_due(now.replace(hour=23, minute=59), now=now) == "Today"


def test_format_due_tomorrow():
    now = datetime(2026, 5, 30, 14, 0)
    tomorrow = now + timedelta(days=1)
    assert format_due(tomorrow, now=now) == "Tomorrow"


def test_format_due_within_week():
    now = datetime(2026, 5, 30, 14, 0)  # Sat
    in_3 = now + timedelta(days=3)  # Tue
    out = format_due(in_3, now=now)
    assert out in ("Mon", "Tue", "Wed")  # weekday name


def test_format_due_same_year():
    now = datetime(2026, 5, 30, 14, 0)
    later = datetime(2026, 9, 15)
    assert format_due(later, now=now) in ("Sep 15", "Sep 15 2026")


def test_format_due_other_year():
    now = datetime(2026, 5, 30, 14, 0)
    later = datetime(2027, 1, 5)
    assert "2027" in format_due(later, now=now)


# ---------------- format_due_iso_input ----------------


def test_format_due_iso_input_none():
    assert format_due_iso_input(None) == ""


def test_format_due_iso_input_date_only():
    assert format_due_iso_input(datetime(2026, 6, 15, 0, 0)) == "2026-06-15"


def test_format_due_iso_input_datetime():
    assert format_due_iso_input(datetime(2026, 6, 15, 14, 30)) == "2026-06-15 14:30"
