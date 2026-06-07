"""Tests for recurring todo behavior."""

from __future__ import annotations

from datetime import datetime, timedelta


def _make_recurring_todo(client, *, description, due, recurrence_seconds, ws_id):
    r = client.post(
        "/api/todos",
        json={"description": description, "parent_workspace_id": ws_id},
    )
    assert r.status_code == 201
    todo = r.json()
    r = client.patch(
        f"/api/todos/{todo['id']}",
        json={"due": due.isoformat(), "recurrence_seconds": recurrence_seconds},
    )
    assert r.status_code == 200
    return r.json()


def test_toggle_recurring_marks_done_advances_due_and_bumps_count(client):
    """Completing a recurring todo: marks done for this cycle, advances `due`
    to next cycle, increments `recurrence_count`. The next list call re-arms
    it once `due` passes."""
    r = client.post("/api/workspaces", json={"description": "W"})
    ws = r.json()
    # Use a past base so the rearm sweep fires on the next list call.
    base = datetime.now() - timedelta(seconds=1)
    todo = _make_recurring_todo(
        client, description="r", due=base, recurrence_seconds=86400, ws_id=ws["id"]
    )
    assert todo["pending"] is True

    out = client.post(f"/api/todos/{todo['id']}/toggle").json()
    assert out["pending"] is False  # done for this cycle
    assert datetime.fromisoformat(out["due"]) == base + timedelta(days=1)
    assert out["recurrence_count"] == 1

    # `due` is now in the future, so listing should NOT re-arm.
    listed = client.get(f"/api/todos/workspace/{ws['id']}").json()
    assert listed[0]["pending"] is False
    assert listed[0]["recurrence_count"] == 1


def test_toggle_non_recurring_flips_normally(client):
    r = client.post("/api/workspaces", json={"description": "W"})
    ws = r.json()
    r = client.post(
        "/api/todos", json={"description": "r", "parent_workspace_id": ws["id"]}
    )
    todo = r.json()
    out = client.post(f"/api/todos/{todo['id']}/toggle").json()
    assert out["pending"] is False
    out = client.post(f"/api/todos/{todo['id']}/toggle").json()
    assert out["pending"] is True


def test_recurring_todo_with_no_due_uses_now(client):
    r = client.post("/api/workspaces", json={"description": "W"})
    ws = r.json()
    r = client.post(
        "/api/todos", json={"description": "r", "parent_workspace_id": ws["id"]}
    )
    todo = r.json()
    client.patch(f"/api/todos/{todo['id']}", json={"recurrence_seconds": 3600})

    before = datetime.now()
    out = client.post(f"/api/todos/{todo['id']}/toggle").json()
    after = datetime.now()

    # Done for this cycle; due is now+1h.
    assert out["pending"] is False
    assert out["recurrence_count"] == 1
    new_due = datetime.fromisoformat(out["due"])
    delta_low = (before + timedelta(hours=1)) - timedelta(seconds=2)
    delta_high = (after + timedelta(hours=1)) + timedelta(seconds=2)
    assert delta_low <= new_due <= delta_high


def test_rearm_after_due_passes(client):
    """Once a recurring todo's due is in the past, listing re-arms it."""
    r = client.post("/api/workspaces", json={"description": "W"})
    ws = r.json()
    # Set due to 2 hours ago, recurrence 1h. After complete, new due = -1h
    # which is in the past → listing re-arms.
    past = datetime.now() - timedelta(hours=2)
    todo = _make_recurring_todo(
        client, description="r", due=past, recurrence_seconds=3600, ws_id=ws["id"]
    )
    out = client.post(f"/api/todos/{todo['id']}/toggle").json()
    # Still in the past after one advance, so the next list call should re-arm.
    assert out["pending"] is False
    listed = client.get(f"/api/todos/workspace/{ws['id']}").json()
    assert listed[0]["pending"] is True
    assert listed[0]["recurrence_count"] == 1  # count is preserved
