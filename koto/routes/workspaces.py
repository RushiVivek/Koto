from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from ..auth import verify_token
from ..database import get_session, get_write_lock
from ..models import Workspace
from ..schemas import (
    ReorderRequest,
    WorkspaceCreate,
    WorkspaceOut,
    WorkspaceUpdate,
)
from ..ws import ws_manager

router = APIRouter(prefix="/api/workspaces", dependencies=[Depends(verify_token)])


def _workspace_to_out(ws: Workspace) -> WorkspaceOut:
    now = datetime.now()
    today = now.date()

    todo_count = len(ws.todos)
    pending_count = 0
    overdue_count = 0
    due_today_count = 0
    for t in ws.todos:
        if t.pending:
            pending_count += 1
            if t.due:
                if t.due < now:
                    overdue_count += 1
                elif t.due.date() == today:
                    due_today_count += 1

    return WorkspaceOut(
        id=ws.id,
        order_index=ws.order_index,
        description=ws.description,
        workspaces=[_workspace_to_out(child) for child in ws.workspaces],
        todo_count=todo_count,
        pending_count=pending_count,
        overdue_count=overdue_count,
        due_today_count=due_today_count,
        done_count=todo_count - pending_count,
    )


def _broadcast_refresh(client_id: Optional[str]) -> None:
    ws_manager.broadcast_threadsafe({"type": "refresh"}, skip_client_id=client_id)


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(session: Session = Depends(get_session)):
    # Re-arm any due recurring todos before computing badges.
    from .todos import _rearm_due_recurring
    with get_write_lock():
        _rearm_due_recurring(session)
    root = session.query(Workspace).filter_by(is_root=True).first()
    if not root:
        return []
    return [_workspace_to_out(ws) for ws in root.workspaces]


@router.post("", response_model=WorkspaceOut, status_code=201)
def create_workspace(
    data: WorkspaceCreate,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    if data.parent_id is not None:
        parent = session.get(Workspace, data.parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="Parent workspace not found")

    with get_write_lock():
        root = session.query(Workspace).filter_by(is_root=True).first()
        parent_id = (
            data.parent_id if data.parent_id is not None
            else (root.id if root else None)
        )
        ws = Workspace(description=data.description, parent_workspace_id=parent_id)
        session.add(ws)
        session.commit()
        session.refresh(ws)
        result = _workspace_to_out(ws)
    _broadcast_refresh(x_client_id)
    return result


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
def update_workspace(
    workspace_id: int,
    data: WorkspaceUpdate,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        ws = session.get(Workspace, workspace_id)
        if not ws or ws.is_root:
            raise HTTPException(status_code=404, detail="Workspace not found")
        fields = data.model_fields_set
        if "description" in fields and data.description is not None:
            ws.description = data.description
        session.commit()
        session.refresh(ws)
        result = _workspace_to_out(ws)
    _broadcast_refresh(x_client_id)
    return result


@router.delete("/{workspace_id}", status_code=204)
def delete_workspace(
    workspace_id: int,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        ws = session.get(Workspace, workspace_id)
        if not ws or ws.is_root:
            raise HTTPException(status_code=404, detail="Workspace not found")
        session.delete(ws)
        session.commit()
    _broadcast_refresh(x_client_id)


@router.post("/{workspace_id}/reorder", status_code=200)
def reorder_workspace(
    workspace_id: int,
    data: ReorderRequest,
    session: Session = Depends(get_session),
    x_client_id: Optional[str] = Header(default=None),
):
    with get_write_lock():
        ws = session.get(Workspace, workspace_id)
        if not ws or ws.is_root:
            raise HTTPException(status_code=404, detail="Workspace not found")

        siblings = (
            session.query(Workspace)
            .filter_by(parent_workspace_id=ws.parent_workspace_id)
            .filter(Workspace.is_root == False)  # noqa: E712 — SQLAlchemy needs ==
            .order_by(Workspace.order_index)
            .all()
        )
        idx = next(i for i, s in enumerate(siblings) if s.id == ws.id)

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
