from datetime import datetime, timedelta
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator

UNTITLED = "Untitled"
MAX_DESCRIPTION_LEN = 2000


class WorkspaceCreate(BaseModel):
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LEN)
    parent_id: Optional[int] = None


class WorkspaceUpdate(BaseModel):
    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LEN)


class WorkspaceOut(BaseModel):
    id: int
    order_index: int
    description: str
    workspaces: List["WorkspaceOut"] = []
    todo_count: int = 0
    pending_count: int = 0
    overdue_count: int = 0
    due_today_count: int = 0
    done_count: int = 0


class TodoCreate(BaseModel):
    description: str = Field(default="", max_length=MAX_DESCRIPTION_LEN)
    parent_workspace_id: Optional[int] = None
    parent_todo_id: Optional[int] = None

    @model_validator(mode="after")
    def _exactly_one_parent(self):
        has_ws = self.parent_workspace_id is not None
        has_todo = self.parent_todo_id is not None
        if has_ws == has_todo:
            raise ValueError(
                "Exactly one of parent_workspace_id or parent_todo_id must be set"
            )
        return self


class TodoUpdate(BaseModel):
    """All fields are optional. Send `null` to clear a nullable field
    (`due`, `recurrence_seconds`). Use `model_fields_set` to distinguish
    "client did not send" from "client sent null"."""

    description: Optional[str] = Field(default=None, max_length=MAX_DESCRIPTION_LEN)
    due: Optional[datetime] = None
    effort: Optional[int] = Field(default=None, ge=0, le=100)
    urgency: Optional[int] = Field(default=None, ge=0, le=10)
    pending: Optional[bool] = None
    recurrence_seconds: Optional[int] = Field(default=None, gt=0)


class TodoOut(BaseModel):
    id: int
    order_index: int
    description: str
    due: Optional[datetime] = None
    effort: int = 0
    recurrence_seconds: Optional[int] = None
    recurrence_count: int = 0
    urgency: int = 1
    pending: bool = True
    parent_workspace_id: Optional[int] = None
    parent_todo_id: Optional[int] = None
    todos: List["TodoOut"] = []

    @classmethod
    def from_model(cls, todo) -> "TodoOut":
        return cls(
            id=todo.id,
            order_index=todo.order_index,
            description=todo.description,
            due=todo.due,
            effort=todo.effort,
            recurrence_seconds=(
                int(todo.recurrence.total_seconds()) if todo.recurrence else None
            ),
            recurrence_count=todo.recurrence_count,
            urgency=todo.urgency,
            pending=todo.pending,
            parent_workspace_id=todo.parent_workspace_id,
            parent_todo_id=todo.parent_todo_id,
            todos=[TodoOut.from_model(t) for t in todo.todos],
        )


class ReorderRequest(BaseModel):
    direction: str = Field(pattern="^(up|down)$")
