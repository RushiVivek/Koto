"""End-to-end tests via FastAPI TestClient: CRUD, auth, ordering, validation."""

from __future__ import annotations


def _create_workspace(client, description="Work", parent_id=None):
    body = {"description": description}
    if parent_id is not None:
        body["parent_id"] = parent_id
    r = client.post("/api/workspaces", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _create_todo(client, **kwargs):
    r = client.post("/api/todos", json=kwargs)
    assert r.status_code == 201, r.text
    return r.json()


# --- Auth ---


def test_no_auth_header_returns_401(client):
    # Use a fresh client without the Authorization header.
    saved = client.headers.pop("Authorization")
    try:
        r = client.get("/api/workspaces")
        assert r.status_code in (401, 403)
    finally:
        client.headers["Authorization"] = saved


def test_bad_token_returns_401(client):
    saved = client.headers["Authorization"]
    client.headers["Authorization"] = "Bearer wrong"
    try:
        r = client.get("/api/workspaces")
        assert r.status_code == 401
    finally:
        client.headers["Authorization"] = saved


# --- Workspaces ---


def test_create_and_list_workspaces(client):
    a = _create_workspace(client, "A")
    b = _create_workspace(client, "B")
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    items = r.json()
    assert [w["id"] for w in items] == [a["id"], b["id"]]
    assert items[0]["order_index"] == 0
    assert items[1]["order_index"] == 1


def test_update_workspace_description(client):
    a = _create_workspace(client, "A")
    r = client.patch(f"/api/workspaces/{a['id']}", json={"description": "renamed"})
    assert r.status_code == 200
    assert r.json()["description"] == "renamed"


def test_delete_workspace_removes_children(client):
    a = _create_workspace(client, "A")
    _create_todo(client, description="t", parent_workspace_id=a["id"])
    r = client.delete(f"/api/workspaces/{a['id']}")
    assert r.status_code == 204
    r = client.get("/api/workspaces")
    assert r.json() == []


def test_reorder_workspaces(client):
    a = _create_workspace(client, "A")
    b = _create_workspace(client, "B")
    c = _create_workspace(client, "C")
    # Move B up -> [B, A, C]
    r = client.post(f"/api/workspaces/{b['id']}/reorder", json={"direction": "up"})
    assert r.status_code == 200
    items = client.get("/api/workspaces").json()
    assert [w["id"] for w in items] == [b["id"], a["id"], c["id"]]


# --- Todos ---


def test_create_todo_under_workspace(client):
    a = _create_workspace(client, "A")
    t = _create_todo(client, description="task", parent_workspace_id=a["id"])
    assert t["parent_workspace_id"] == a["id"]
    assert t["parent_todo_id"] is None
    assert t["pending"] is True


def test_create_subtodo(client):
    a = _create_workspace(client, "A")
    parent = _create_todo(client, description="p", parent_workspace_id=a["id"])
    child = _create_todo(client, description="c", parent_todo_id=parent["id"])
    assert child["parent_todo_id"] == parent["id"]
    assert child["parent_workspace_id"] is None


def test_create_todo_rejects_no_parent(client):
    r = client.post("/api/todos", json={"description": "x"})
    assert r.status_code == 422


def test_create_todo_rejects_both_parents(client):
    a = _create_workspace(client, "A")
    p = _create_todo(client, description="p", parent_workspace_id=a["id"])
    r = client.post(
        "/api/todos",
        json={
            "description": "x",
            "parent_workspace_id": a["id"],
            "parent_todo_id": p["id"],
        },
    )
    assert r.status_code == 422


def test_toggle_todo_flips_pending(client):
    a = _create_workspace(client, "A")
    t = _create_todo(client, description="x", parent_workspace_id=a["id"])
    r = client.post(f"/api/todos/{t['id']}/toggle")
    assert r.status_code == 200
    assert r.json()["pending"] is False
    r = client.post(f"/api/todos/{t['id']}/toggle")
    assert r.json()["pending"] is True


def test_clear_due_via_null(client):
    a = _create_workspace(client, "A")
    t = _create_todo(client, description="x", parent_workspace_id=a["id"])
    client.patch(f"/api/todos/{t['id']}", json={"due": "2026-12-31T10:00:00"})
    r = client.get(f"/api/todos/{t['id']}")
    assert r.json()["due"] is not None
    client.patch(f"/api/todos/{t['id']}", json={"due": None})
    r = client.get(f"/api/todos/{t['id']}")
    assert r.json()["due"] is None


def test_clear_recurrence_via_null(client):
    a = _create_workspace(client, "A")
    t = _create_todo(client, description="x", parent_workspace_id=a["id"])
    client.patch(f"/api/todos/{t['id']}", json={"recurrence_seconds": 3600})
    assert client.get(f"/api/todos/{t['id']}").json()["recurrence_seconds"] == 3600
    client.patch(f"/api/todos/{t['id']}", json={"recurrence_seconds": None})
    assert client.get(f"/api/todos/{t['id']}").json()["recurrence_seconds"] is None


def test_urgency_out_of_bounds_rejected(client):
    a = _create_workspace(client, "A")
    t = _create_todo(client, description="x", parent_workspace_id=a["id"])
    assert client.patch(f"/api/todos/{t['id']}", json={"urgency": -1}).status_code == 422
    assert client.patch(f"/api/todos/{t['id']}", json={"urgency": 999}).status_code == 422
    assert client.patch(f"/api/todos/{t['id']}", json={"urgency": 5}).status_code == 200


def test_description_max_length(client):
    a = _create_workspace(client, "A")
    long_desc = "x" * 3000
    r = client.post(
        "/api/todos",
        json={"description": long_desc, "parent_workspace_id": a["id"]},
    )
    assert r.status_code == 422


def test_workspace_count_fields(client):
    from datetime import datetime, timedelta

    a = _create_workspace(client, "A")
    t1 = _create_todo(client, description="t1", parent_workspace_id=a["id"])
    _create_todo(client, description="t2", parent_workspace_id=a["id"])

    past = (datetime.now() - timedelta(days=1)).isoformat()
    client.patch(f"/api/todos/{t1['id']}", json={"due": past})

    items = client.get("/api/workspaces").json()
    ws = next(w for w in items if w["id"] == a["id"])
    assert ws["todo_count"] == 2
    assert ws["pending_count"] == 2
    assert ws["overdue_count"] == 1
    assert ws["done_count"] == 0


def test_ws_hello_escapes_client_id(client):
    """Bug 3: the hello message must use json.dumps so a malicious client_id
    can't inject characters that produce malformed JSON."""
    import json as _json

    bad_id = 'evil"id\\with\\backslashes'
    with client.websocket_connect(
        f"/ws?token=test-token&client_id={bad_id}"
    ) as ws:
        msg = ws.receive_text()
        # Must be valid JSON.
        parsed = _json.loads(msg)
        assert parsed == {"type": "hello", "client_id": bad_id}


def test_create_workspace_rejects_missing_parent(client):
    """Bug 1: parent_id pointing at a non-existent workspace must 404, not
    silently persist an orphan."""
    r = client.post("/api/workspaces", json={"description": "orphan", "parent_id": 999})
    assert r.status_code == 404
    # And parent_id=0 (special case the prior fix exposed).
    r = client.post("/api/workspaces", json={"description": "orphan", "parent_id": 0})
    assert r.status_code == 404


def test_create_workspace_under_existing_parent(client):
    a = _create_workspace(client, "A")
    r = client.post(
        "/api/workspaces",
        json={"description": "child", "parent_id": a["id"]},
    )
    assert r.status_code == 201
    # Should appear nested under A.
    items = client.get("/api/workspaces").json()
    a_out = next(w for w in items if w["id"] == a["id"])
    assert any(c["description"] == "child" for c in a_out["workspaces"])


def test_completion_propagates_through_http(client):
    """B1/B2 via the HTTP layer: complete the top of a 3-level chain via toggle,
    all descendants should be marked done."""
    a = _create_workspace(client, "A")
    grand = _create_todo(client, description="grand", parent_workspace_id=a["id"])
    parent = _create_todo(client, description="parent", parent_todo_id=grand["id"])
    leaf = _create_todo(client, description="leaf", parent_todo_id=parent["id"])

    client.post(f"/api/todos/{grand['id']}/toggle")

    g = client.get(f"/api/todos/{grand['id']}").json()
    p = client.get(f"/api/todos/{parent['id']}").json()
    l = client.get(f"/api/todos/{leaf['id']}").json()
    assert g["pending"] is False
    assert p["pending"] is False
    assert l["pending"] is False


def test_x_client_id_header_actually_skips_originator(client, monkeypatch):
    """Mutating with X-Client-Id: <id> must trigger broadcast_threadsafe with
    skip_client_id=<id>. Capture the call and assert."""
    from koto import ws as ws_mod

    captured = []
    real = ws_mod.ws_manager.broadcast_threadsafe

    def fake(message, skip_client_id=None):
        captured.append((message, skip_client_id))

    monkeypatch.setattr(ws_mod.ws_manager, "broadcast_threadsafe", fake)
    # Re-bind on the route module too (it imported ws_manager directly).
    from koto.routes import workspaces as routes_ws
    monkeypatch.setattr(routes_ws.ws_manager, "broadcast_threadsafe", fake)

    r = client.post(
        "/api/workspaces",
        json={"description": "A"},
        headers={"X-Client-Id": "abc-client"},
    )
    assert r.status_code == 201
    assert captured, "broadcast_threadsafe was not called"
    msg, skip = captured[-1]
    assert msg == {"type": "refresh"}
    assert skip == "abc-client"

    # Without the header, broadcast should fire with skip=None.
    captured.clear()
    r = client.post("/api/workspaces", json={"description": "B"})
    assert r.status_code == 201
    assert captured[-1][1] is None

    monkeypatch.setattr(ws_mod.ws_manager, "broadcast_threadsafe", real)
