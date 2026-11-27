from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import CheckConstraint, ForeignKey, event, inspect, select, text, update
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


class Base(DeclarativeBase):
    pass


class Workspace(Base):
    __tablename__ = "workspace"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_index: Mapped[int] = mapped_column(default=-1)
    description: Mapped[str] = mapped_column(default="")
    is_root: Mapped[bool] = mapped_column(default=False)

    parent_workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspace.id"), default=None, nullable=True
    )
    parent_workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace",
        back_populates="workspaces",
        remote_side=[id],
    )
    workspaces: Mapped[List["Workspace"]] = relationship(
        "Workspace",
        back_populates="parent_workspace",
        cascade="all, delete-orphan",
        order_by="Workspace.order_index",
    )
    todos: Mapped[List["Todo"]] = relationship(
        "Todo",
        back_populates="parent_workspace",
        cascade="all, delete-orphan",
        order_by="Todo.order_index",
    )


class Todo(Base):
    __tablename__ = "todo"
    __table_args__ = (
        # Exactly one of parent_workspace_id / parent_todo_id must be set.
        CheckConstraint(
            "(parent_workspace_id IS NULL) != (parent_todo_id IS NULL)",
            name="ck_todo_exactly_one_parent",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    order_index: Mapped[int] = mapped_column(default=-1)
    description: Mapped[str] = mapped_column(default="")
    due: Mapped[Optional[datetime]] = mapped_column(default=None, nullable=True)
    effort: Mapped[int] = mapped_column(default=0)
    recurrence: Mapped[Optional[timedelta]] = mapped_column(
        default=None, nullable=True
    )
    recurrence_count: Mapped[int] = mapped_column(default=0)
    urgency: Mapped[int] = mapped_column(default=1)
    pending: Mapped[bool] = mapped_column(default=True)

    parent_workspace_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspace.id"), nullable=True
    )
    parent_workspace: Mapped[Optional["Workspace"]] = relationship(
        "Workspace",
        back_populates="todos",
    )

    parent_todo_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("todo.id"), nullable=True
    )
    parent_todo: Mapped[Optional["Todo"]] = relationship(
        "Todo",
        back_populates="todos",
        remote_side=[id],
    )
    todos: Mapped[List["Todo"]] = relationship(
        "Todo",
        back_populates="parent_todo",
        cascade="all, delete-orphan",
        order_by="Todo.order_index",
    )


# --- SQLAlchemy event hooks ---
#
# Hooks rely on `parent_todo_id` and `parent_workspace_id` not changing during
# an update (only the API doesn't expose re-parenting). Direct SQL or future
# re-parent endpoints would need to revisit propagation logic. Hook order is
# undefined — each is written to be independently safe.


def _pending_changed(target: "Todo") -> bool:
    history = inspect(target).attrs.pending.history
    return history.has_changes()


@event.listens_for(Workspace, "before_insert")
def fix_workspace_order(_, connection, target: Workspace):
    if target.is_root:
        return
    if target.order_index is None or target.order_index == -1:
        result = connection.execute(
            text(
                "SELECT COUNT(*) FROM workspace WHERE parent_workspace_id = :pid"
            ),
            {"pid": target.parent_workspace_id},
        )
        target.order_index = result.scalar() or 0


@event.listens_for(Todo, "before_insert")
def fix_todo_order(_, connection, target: Todo):
    """Place a new todo after its pending siblings but above the completed
    ones trailing the list, shifting those down by one."""
    if target.order_index is not None and target.order_index != -1:
        return
    if target.parent_workspace_id:
        parent_col, parent_id = "parent_workspace_id", target.parent_workspace_id
    else:
        parent_col, parent_id = "parent_todo_id", target.parent_todo_id
    siblings = connection.execute(
        text(
            f"SELECT id, order_index, pending FROM todo WHERE {parent_col} = :pid "
            "ORDER BY order_index, id"
        ),
        {"pid": parent_id},
    ).all()
    trailing_done = []
    for row in reversed(siblings):
        if row.pending:
            break
        trailing_done.append(row.id)
    if not trailing_done or target.pending is False:
        target.order_index = (siblings[-1].order_index + 1) if siblings else 0
        return
    target.order_index = siblings[len(siblings) - len(trailing_done)].order_index
    connection.execute(
        update(Todo)
        .where(Todo.id.in_(trailing_done))
        .values(order_index=Todo.order_index + 1)
    )


@event.listens_for(Todo, "after_insert")
def reopen_parents_when_child_added(_, connection, target: Todo):
    """When a new pending sub-todo is added under a completed parent, re-open
    the parent (and ancestors) so they reflect outstanding work."""
    if not target.pending or not target.parent_todo_id:
        return

    parent_id = target.parent_todo_id
    while parent_id:
        row = connection.execute(
            text("SELECT pending, parent_todo_id FROM todo WHERE id = :id"),
            {"id": parent_id},
        ).first()
        if row is None:
            return
        parent_pending, grandparent_id = row
        if parent_pending:
            return
        connection.execute(
            update(Todo).where(Todo.id == parent_id).values(pending=True)
        )
        parent_id = grandparent_id


def _all_descendants(connection, root_id: int) -> list[int]:
    """Collect all descendant todo ids of `root_id` (BFS), exclusive of root."""
    result: list[int] = []
    frontier = [root_id]
    while frontier:
        rows = connection.execute(
            text(
                "SELECT id FROM todo WHERE parent_todo_id IN ("
                + ",".join(str(int(i)) for i in frontier)
                + ")"
            )
        ).all()
        children = [r[0] for r in rows]
        result.extend(children)
        frontier = children
    return result


@event.listens_for(Todo, "before_update")
def propagate_completion_down(_, connection, target: Todo):
    """When a todo is marked complete, mark all descendants complete too
    (full subtree, not just direct children)."""
    if target.pending or not _pending_changed(target):
        return
    descendants = _all_descendants(connection, target.id)
    if not descendants:
        return
    connection.execute(
        update(Todo).where(Todo.id.in_(descendants)).values(pending=False)
    )


@event.listens_for(Todo, "before_update")
def propagate_pending_up(_, connection, target: Todo):
    """When a todo is re-opened, walk up the full ancestor chain and re-open
    each ancestor (stop early if an ancestor is already pending).

    For recurring ancestors, also undo the cycle-advance done when they were
    auto-completed: roll back `due` and decrement `recurrence_count`.
    """
    if not target.pending or not target.parent_todo_id or not _pending_changed(target):
        return

    parent_id = target.parent_todo_id
    while parent_id:
        row = connection.execute(
            select(
                Todo.pending,
                Todo.recurrence,
                Todo.due,
                Todo.recurrence_count,
                Todo.parent_todo_id,
            ).where(Todo.id == parent_id)
        ).first()
        if row is None:
            return
        parent_pending, recurrence, due, rec_count, grandparent_id = row
        if parent_pending:
            return  # already pending, ancestors above also pending

        values: dict = {"pending": True}
        if recurrence is not None:
            if (rec_count or 0) > 0:
                values["recurrence_count"] = rec_count - 1
            if due is not None:
                values["due"] = due - recurrence
        connection.execute(
            update(Todo).where(Todo.id == parent_id).values(**values)
        )
        parent_id = grandparent_id


@event.listens_for(Todo, "before_update")
def auto_complete_parent_when_all_done(_, connection, target: Todo):
    """When the last pending child of a parent is completed, complete the
    parent too — and walk up cascading.

    Recurring parents are completed the same way; they additionally have
    their `due` advanced and `recurrence_count` bumped — same semantics as
    a manual toggle. Re-arming happens lazily on the next list call once
    `due` passes.
    """
    if target.pending or not _pending_changed(target) or not target.parent_todo_id:
        return

    from datetime import datetime as _dt  # local import; avoid module reorg

    current_id = target.id
    parent_id = target.parent_todo_id

    while parent_id:
        pending_siblings = connection.execute(
            text(
                "SELECT COUNT(*) FROM todo "
                "WHERE parent_todo_id = :pid AND pending = 1 AND id != :cid"
            ),
            {"pid": parent_id, "cid": current_id},
        ).scalar()

        if pending_siblings > 0:
            return

        parent_row = connection.execute(
            select(
                Todo.recurrence,
                Todo.due,
                Todo.recurrence_count,
                Todo.parent_todo_id,
            ).where(Todo.id == parent_id)
        ).first()
        if parent_row is None:
            return
        recurrence, due, rec_count, grandparent_id = parent_row

        values = {"pending": False}
        if recurrence is not None:
            base = due or _dt.now()
            values["due"] = base + recurrence
            values["recurrence_count"] = (rec_count or 0) + 1
        connection.execute(
            update(Todo).where(Todo.id == parent_id).values(**values)
        )

        current_id = parent_id
        parent_id = grandparent_id


