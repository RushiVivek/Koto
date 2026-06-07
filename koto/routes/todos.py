from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from ..auth import verify_token
from ..database import get_session, get_write_lock
from ..models import Todo, Workspace
from ..schemas import ReorderRequest, TodoCreate, TodoOut, TodoUpdate
from ..ws import ws_manager


def _rearm_due_recurring(session: Session) -> None:
    """Re-open completed recurring todos whose `due` is now in the past, plus
    their descendants. Idempotent. Cheap when there's nothing to do.
    """
    now = datetime.now()
    candidates = (
        session.query(Todo)
        .filter(
            Todo.recurrence.is_not(None),
            Todo.pending == False,  # noqa: E712
            Todo.due.is_not(None),
            Todo.due <= now,
        )
        .all()
    )
    if not candidates:
        return
    for todo in candidates:
        todo.pending = True
        # Re-open all descendants too so the subtree is "fresh" for this cycle.
        stack = list(todo.todos)
        while stack:
            child = stack.pop()
            child.pending = True
            stack.extend(child.todos)
    session.commit()

router = APIRouter(prefix="/api/todos", dependencies=[Depends(verify_token)])


def _broadcast_refresh(client_id: Optional[str]) -> None:
    ws_manager.broadcast_threadsafe({"type": "refresh"}, skip_client_id=client_id)


@router.get("/workspace/{workspace_id}", response_model=list[TodoOut])
def list_todos(workspace_id: int, session: Session = Depends(get_session)):
    ws = session.get(Workspace, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    with get_write_lock():
        _rearm_due_recurring(session)
    session.refresh(ws)
    return [TodoOut.from_model(t) for t in ws.todos]


@router.get("/{todo_id}", response_model=TodoOut)
def get_todo(todo_id: int, session: Session = Depends(get_session)):
    todo = session.get(Todo, todo_id)
    if not todo:
        raise HTTPException(status_code=404, detail="Todo not found")
    return TodoOut.from_model(todo)


@router.post("", response_model=TodoOut, status_code=201)
def create_todo(
    data: TodoCreate,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    # Schema validator already enforces exactly-one parent.
    if data.parent_workspace_id is not None:
        if not session.get(Workspace, data.parent_workspace_id):
            raise HTTPException(status_code=404, detail="Parent workspace not found")
    if data.parent_todo_id is not None:
        if not session.get(Todo, data.parent_todo_id):
            raise HTTPException(status_code=404, detail="Parent todo not found")

    with get_write_lock():
        todo = Todo(
            description=data.description,
            parent_workspace_id=data.parent_workspace_id,
            parent_todo_id=data.parent_todo_id,
        )
        session.add(todo)
        session.commit()
        session.refresh(todo)
        result = TodoOut.from_model(todo)
    _broadcast_refresh(x_client_id)
    return result


@router.patch("/{todo_id}", response_model=TodoOut)
def update_todo(
    todo_id: int,
    data: TodoUpdate,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        todo = session.get(Todo, todo_id)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")

        fields = data.model_fields_set

        if "description" in fields and data.description is not None:
            todo.description = data.description
        if "due" in fields:
            todo.due = data.due  # may be None to clear
        if "effort" in fields and data.effort is not None:
            todo.effort = data.effort
        if "urgency" in fields and data.urgency is not None:
            todo.urgency = data.urgency
        if "pending" in fields and data.pending is not None:
            todo.pending = data.pending
        if "recurrence_seconds" in fields:
            if data.recurrence_seconds is None:
                todo.recurrence = None
            else:
                todo.recurrence = timedelta(seconds=data.recurrence_seconds)

        session.commit()
        session.refresh(todo)
        result = TodoOut.from_model(todo)
    _broadcast_refresh(x_client_id)
    return result


@router.delete("/{todo_id}", status_code=204)
def delete_todo(
    todo_id: int,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        todo = session.get(Todo, todo_id)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")
        session.delete(todo)
        session.commit()
    _broadcast_refresh(x_client_id)


@router.post("/{todo_id}/toggle", response_model=TodoOut)
def toggle_todo(
    todo_id: int,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        todo = session.get(Todo, todo_id)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")

        new_pending = not todo.pending

        if todo.recurrence:
            if not new_pending:
                # Completing this cycle: advance due, bump count.
                todo.pending = False
                todo.recurrence_count = (todo.recurrence_count or 0) + 1
                base = todo.due or datetime.now()
                todo.due = base + todo.recurrence
            else:
                # Undoing a completion: roll back the previous advance.
                todo.pending = True
                if (todo.recurrence_count or 0) > 0:
                    todo.recurrence_count -= 1
                if todo.due is not None:
                    todo.due = todo.due - todo.recurrence
        else:
            todo.pending = new_pending

        session.commit()
        session.refresh(todo)
        result = TodoOut.from_model(todo)
    _broadcast_refresh(x_client_id)
    return result


def _sort_siblings_completed_last(siblings: list[Todo]) -> None:
    """Reassign siblings' order_index so pending todos come first
    (keeping their relative order), then completed todos."""
    pending = [s for s in siblings if s.pending]
    done = [s for s in siblings if not s.pending]
    for i, s in enumerate(pending + done):
        s.order_index = i


@router.post("/workspace/{workspace_id}/sort_completed", status_code=200)
def sort_workspace_completed(
    workspace_id: int,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        ws = session.get(Workspace, workspace_id)
        if not ws:
            raise HTTPException(status_code=404, detail="Workspace not found")
        siblings = (
            session.query(Todo)
            .filter_by(parent_workspace_id=workspace_id)
            .order_by(Todo.order_index)
            .all()
        )
        _sort_siblings_completed_last(siblings)
        session.commit()
    _broadcast_refresh(x_client_id)
    return {"ok": True}


@router.post("/{todo_id}/sort_completed", status_code=200)
def sort_todo_completed(
    todo_id: int,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    """Sort the children of a todo (its sub-todos) so completed ones go last."""
    with get_write_lock():
        todo = session.get(Todo, todo_id)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")
        siblings = (
            session.query(Todo)
            .filter_by(parent_todo_id=todo_id)
            .order_by(Todo.order_index)
            .all()
        )
        _sort_siblings_completed_last(siblings)
        session.commit()
    _broadcast_refresh(x_client_id)
    return {"ok": True}


@router.post("/{todo_id}/reorder", status_code=200)
def reorder_todo(
    todo_id: int,
    data: ReorderRequest,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        todo = session.get(Todo, todo_id)
        if not todo:
            raise HTTPException(status_code=404, detail="Todo not found")

        if todo.parent_workspace_id:
            siblings = (
                session.query(Todo)
                .filter_by(parent_workspace_id=todo.parent_workspace_id)
                .order_by(Todo.order_index)
                .all()
            )
        else:
            siblings = (
                session.query(Todo)
                .filter_by(parent_todo_id=todo.parent_todo_id)
                .order_by(Todo.order_index)
                .all()
            )

        idx = next(i for i, s in enumerate(siblings) if s.id == todo.id)

        if data.direction == "up" and idx > 0:
            siblings[idx].order_index, siblings[idx - 1].order_index = (
                siblings[idx - 1].order_index,
                siblings[idx].order_index,
            )
        elif data.direction == "down" and idx < len(siblings) - 1:
            siblings[idx].order_index, siblings[idx + 1].order_index = (
                siblings[idx + 1].order_index,
                siblings[idx].order_index,
            )
        session.commit()
    _broadcast_refresh(x_client_id)
    return {"ok": True}
