"""Tests for SQLAlchemy event hooks: completion propagation, ordering."""

from __future__ import annotations

import pytest

from koto.models import Todo, Workspace


def _root(session) -> Workspace:
    return session.query(Workspace).filter_by(is_root=True).first()


def _make_workspace(session, name="Work") -> Workspace:
    ws = Workspace(description=name, parent_workspace_id=_root(session).id)
    session.add(ws)
    session.commit()
    session.refresh(ws)
    return ws


def _make_todo(session, *, parent_workspace_id=None, parent_todo_id=None, **kwargs) -> Todo:
    t = Todo(
        parent_workspace_id=parent_workspace_id,
        parent_todo_id=parent_todo_id,
        **kwargs,
    )
    session.add(t)
    session.commit()
    session.refresh(t)
    return t


def test_root_workspace_exists(session):
    root = _root(session)
    assert root is not None
    assert root.is_root is True


def test_workspace_order_index_assigned_on_insert(session):
    a = _make_workspace(session, "A")
    b = _make_workspace(session, "B")
    c = _make_workspace(session, "C")
    assert a.order_index == 0
    assert b.order_index == 1
    assert c.order_index == 2


def test_todo_order_index_assigned_under_workspace(session):
    ws = _make_workspace(session)
    t1 = _make_todo(session, parent_workspace_id=ws.id, description="t1")
    t2 = _make_todo(session, parent_workspace_id=ws.id, description="t2")
    assert t1.order_index == 0
    assert t2.order_index == 1


def test_todo_order_index_assigned_under_parent_todo(session):
    ws = _make_workspace(session)
    parent = _make_todo(session, parent_workspace_id=ws.id, description="parent")
    c1 = _make_todo(session, parent_todo_id=parent.id, description="c1")
    c2 = _make_todo(session, parent_todo_id=parent.id, description="c2")
    assert c1.order_index == 0
    assert c2.order_index == 1


def _order(session, ws_id=None, parent_todo_id=None) -> list[str]:
    session.expire_all()
    q = session.query(Todo)
    q = q.filter_by(parent_workspace_id=ws_id) if ws_id else q.filter_by(parent_todo_id=parent_todo_id)
    return [t.description for t in q.order_by(Todo.order_index)]


def test_new_todo_goes_above_trailing_completed(session):
    ws = _make_workspace(session)
    _make_todo(session, parent_workspace_id=ws.id, description="a")
    _make_todo(session, parent_workspace_id=ws.id, description="done1", pending=False)
    _make_todo(session, parent_workspace_id=ws.id, description="done2", pending=False)
    _make_todo(session, parent_workspace_id=ws.id, description="b")
    assert _order(session, ws_id=ws.id) == ["a", "b", "done1", "done2"]


def test_new_todo_keeps_completed_in_middle(session):
    # Only the trailing completed run is skipped; a done todo between
    # pending ones stays where the user put it.
    ws = _make_workspace(session)
    _make_todo(session, parent_workspace_id=ws.id, description="a")
    x = _make_todo(session, parent_workspace_id=ws.id, description="x")
    _make_todo(session, parent_workspace_id=ws.id, description="b")
    x.pending = False
    session.commit()
    _make_todo(session, parent_workspace_id=ws.id, description="c")
    assert _order(session, ws_id=ws.id) == ["a", "x", "b", "c"]


def test_new_subtodo_goes_above_completed(session):
    ws = _make_workspace(session)
    parent = _make_todo(session, parent_workspace_id=ws.id, description="p")
    _make_todo(session, parent_todo_id=parent.id, description="a")
    _make_todo(session, parent_todo_id=parent.id, description="done", pending=False)
    _make_todo(session, parent_todo_id=parent.id, description="b")
    assert _order(session, parent_todo_id=parent.id) == ["a", "b", "done"]


def test_completion_propagates_down(session):
    ws = _make_workspace(session)
    parent = _make_todo(session, parent_workspace_id=ws.id, description="parent")
    c1 = _make_todo(session, parent_todo_id=parent.id, description="c1")
    c2 = _make_todo(session, parent_todo_id=parent.id, description="c2")

    parent.pending = False
    session.commit()
    session.refresh(c1)
    session.refresh(c2)
    assert c1.pending is False
    assert c2.pending is False


def test_pending_propagates_up(session):
    ws = _make_workspace(session)
    parent = _make_todo(session, parent_workspace_id=ws.id, description="parent")
    child = _make_todo(session, parent_todo_id=parent.id, description="c")

    # Complete everything first.
    parent.pending = False
    session.commit()
    session.refresh(parent)
    session.refresh(child)
    assert parent.pending is False
    assert child.pending is False

    # Reopen child -> parent should re-open.
    child.pending = True
    session.commit()
    session.refresh(parent)
    assert parent.pending is True


def test_auto_complete_parent_when_all_children_done(session):
    ws = _make_workspace(session)
    parent = _make_todo(session, parent_workspace_id=ws.id, description="parent")
    c1 = _make_todo(session, parent_todo_id=parent.id, description="c1")
    c2 = _make_todo(session, parent_todo_id=parent.id, description="c2")

    c1.pending = False
    session.commit()
    session.refresh(parent)
    assert parent.pending is True  # one child still pending

    c2.pending = False
    session.commit()
    session.refresh(parent)
    assert parent.pending is False  # both children done -> parent auto-completes


def test_auto_complete_cascades_up_multiple_levels(session):
    ws = _make_workspace(session)
    grand = _make_todo(session, parent_workspace_id=ws.id, description="grand")
    parent = _make_todo(session, parent_todo_id=grand.id, description="parent")
    leaf = _make_todo(session, parent_todo_id=parent.id, description="leaf")

    leaf.pending = False
    session.commit()
    session.refresh(parent)
    session.refresh(grand)
    assert parent.pending is False
    assert grand.pending is False


def test_reopen_parent_when_pending_child_added(session):
    ws = _make_workspace(session)
    parent = _make_todo(session, parent_workspace_id=ws.id, description="parent")
    child = _make_todo(session, parent_todo_id=parent.id, description="c")

    child.pending = False
    session.commit()
    session.refresh(parent)
    assert parent.pending is False

    # New pending sub-todo should reopen the parent.
    _make_todo(session, parent_todo_id=parent.id, description="new sub")
    session.refresh(parent)
    assert parent.pending is True


def test_description_change_does_not_propagate_pending(session):
    ws = _make_workspace(session)
    parent = _make_todo(session, parent_workspace_id=ws.id, description="parent")
    c1 = _make_todo(session, parent_todo_id=parent.id, description="c1")

    parent.description = "renamed"
    session.commit()
    session.refresh(c1)
    session.refresh(parent)
    assert parent.pending is True
    assert c1.pending is True


def test_completion_propagates_down_multiple_levels(session):
    """Marking a top-level todo complete should mark *all* descendants complete,
    not just direct children."""
    ws = _make_workspace(session)
    grand = _make_todo(session, parent_workspace_id=ws.id, description="grand")
    parent = _make_todo(session, parent_todo_id=grand.id, description="parent")
    leaf = _make_todo(session, parent_todo_id=parent.id, description="leaf")
    deeper = _make_todo(session, parent_todo_id=leaf.id, description="deeper")

    grand.pending = False
    session.commit()
    for t in (parent, leaf, deeper):
        session.refresh(t)
    assert parent.pending is False
    assert leaf.pending is False
    assert deeper.pending is False


def test_pending_propagates_up_multiple_levels(session):
    """Re-opening a deeply-nested todo should re-open *all* ancestors."""
    ws = _make_workspace(session)
    grand = _make_todo(session, parent_workspace_id=ws.id, description="grand")
    parent = _make_todo(session, parent_todo_id=grand.id, description="parent")
    leaf = _make_todo(session, parent_todo_id=parent.id, description="leaf")

    grand.pending = False
    session.commit()
    for t in (parent, leaf):
        session.refresh(t)
    assert leaf.pending is False

    leaf.pending = True
    session.commit()
    session.refresh(parent)
    session.refresh(grand)
    assert parent.pending is True
    assert grand.pending is True


def test_foreign_keys_pragma_enabled(session):
    """Bug 2: FK enforcement must be ON at the DB level."""
    result = session.execute(__import__("sqlalchemy").text("PRAGMA foreign_keys")).first()
    assert result[0] == 1


def test_recurring_parent_completes_with_children_then_rearms_on_due(session):
    """A recurring parent is completed when its last child completes; the
    route-level sweep re-arms it once `due` is in the past."""
    from datetime import datetime, timedelta
    from koto.routes.todos import _rearm_due_recurring

    ws = _make_workspace(session)
    # Use a far-past due so even after cascade advances by 1 day, it's still past.
    parent = _make_todo(
        session,
        parent_workspace_id=ws.id,
        description="recurring parent",
        due=datetime.now() - timedelta(days=3),
        recurrence=timedelta(days=1),
    )
    c = _make_todo(session, parent_todo_id=parent.id, description="c")

    # Completing the only child completes the parent and bumps its count/due.
    c.pending = False
    session.commit()
    session.refresh(parent)
    assert parent.pending is False
    assert parent.recurrence_count == 1

    # Due is still in the past after the +1d advance, so listing re-arms.
    _rearm_due_recurring(session)
    session.refresh(parent)
    session.refresh(c)
    assert parent.pending is True
    assert c.pending is True
    # Count is preserved across re-arm.
    assert parent.recurrence_count == 1


def test_cascade_advances_recurring_parent_due_and_count(session):
    """When all children complete, a recurring parent's `due` advances and
    `recurrence_count` increments — same as a manual toggle."""
    from datetime import datetime, timedelta

    ws = _make_workspace(session)
    base = datetime(2026, 6, 1, 10, 0, 0)
    parent = _make_todo(
        session,
        parent_workspace_id=ws.id,
        description="weekly parent",
        due=base,
        recurrence=timedelta(days=7),
    )
    c1 = _make_todo(session, parent_todo_id=parent.id, description="c1")
    c2 = _make_todo(session, parent_todo_id=parent.id, description="c2")

    c1.pending = False
    session.commit()
    session.refresh(parent)
    assert parent.pending is True  # one child still pending

    c2.pending = False
    session.commit()
    session.refresh(parent)
    assert parent.pending is False
    assert parent.due == base + timedelta(days=7)
    assert parent.recurrence_count == 1


def test_undo_recurring_rolls_back_due_and_count(session):
    """Reopening a recurring parent (via child re-open) rolls back due and
    decrements count."""
    from datetime import datetime, timedelta

    ws = _make_workspace(session)
    base = datetime(2026, 6, 1, 10, 0, 0)
    parent = _make_todo(
        session,
        parent_workspace_id=ws.id,
        description="weekly parent",
        due=base,
        recurrence=timedelta(days=7),
    )
    c = _make_todo(session, parent_todo_id=parent.id, description="c")

    c.pending = False
    session.commit()
    session.refresh(parent)
    assert parent.pending is False
    assert parent.due == base + timedelta(days=7)
    assert parent.recurrence_count == 1

    # Reopen the child — parent rolls back.
    c.pending = True
    session.commit()
    session.refresh(parent)
    assert parent.pending is True
    assert parent.due == base
    assert parent.recurrence_count == 0


def test_toggle_recurring_advances_due_and_increments_count(session):
    """Toggling a recurring todo: marks done, advances due, bumps count."""
    from datetime import datetime, timedelta
    from koto.routes.todos import toggle_todo

    ws = _make_workspace(session)
    base_due = datetime(2026, 6, 1, 10, 0, 0)
    todo = _make_todo(
        session,
        parent_workspace_id=ws.id,
        description="weekly",
        due=base_due,
        recurrence=timedelta(days=7),
    )

    toggle_todo(todo.id, session=session, x_client_id=None)
    session.refresh(todo)
    assert todo.pending is False
    assert todo.due == base_due + timedelta(days=7)
    assert todo.recurrence_count == 1


def test_check_constraint_rejects_no_parent(session):
    """A todo with neither parent should violate the CHECK constraint at the DB level."""
    from sqlalchemy.exc import IntegrityError

    t = Todo(description="orphan")
    session.add(t)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_check_constraint_rejects_both_parents(session):
    from sqlalchemy.exc import IntegrityError

    ws = _make_workspace(session)
    p = _make_todo(session, parent_workspace_id=ws.id, description="parent")
    t = Todo(description="bad", parent_workspace_id=ws.id, parent_todo_id=p.id)
    session.add(t)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
