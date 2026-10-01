"""Request and response shapes for the task and subtask routes.

On the PATCH bodies, a field that is *left out* is not changed, while a field
sent as ``null`` is cleared. That is how a client unassigns a task or removes
its due date. Fields a task cannot be without (title, status) refuse null.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, ClassVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

from server.schemas.auth import UserOut, to_user_out
from shared.statuses import TaskStatus

if TYPE_CHECKING:
    from server.models.subtask import Subtask
    from server.models.task import Task

MAX_TITLE_LENGTH = 200
MAX_TASK_DESCRIPTION_LENGTH = 5000


def _blank_to_none(value: str | None) -> str | None:
    return value or None


#: An all-whitespace description means "no description", not an empty one.
#: (Whitespace is stripped first by ``str_strip_whitespace``.)
Description = Annotated[
    str | None,
    Field(max_length=MAX_TASK_DESCRIPTION_LENGTH),
    AfterValidator(_blank_to_none),
]


class _NoNullRequiredFields(BaseModel):
    """Rejects an explicit null for fields listed in ``_required``."""

    _required: ClassVar[tuple[str, ...]] = ("title", "status")

    @model_validator(mode="after")
    def required_fields_are_not_null(self) -> "_NoNullRequiredFields":
        for field in self._required:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class TaskCreate(BaseModel):
    """Body of POST /projects/{project_id}/tasks."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Description = None
    assignee_id: int | None = None
    due_date: date | None = None
    status: TaskStatus = TaskStatus.TODO


class TaskUpdate(_NoNullRequiredFields):
    """Body of PATCH /tasks/{id}. Only the fields sent are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Description = None
    assignee_id: int | None = None
    due_date: date | None = None
    status: TaskStatus | None = None


class SubtaskCreate(BaseModel):
    """Body of POST /tasks/{task_id}/subtasks."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    assignee_id: int | None = None
    due_date: date | None = None
    status: TaskStatus = TaskStatus.TODO


class SubtaskUpdate(_NoNullRequiredFields):
    """Body of PATCH /subtasks/{id}. Only the fields sent are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: str | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    assignee_id: int | None = None
    due_date: date | None = None
    status: TaskStatus | None = None


class SubtaskOut(BaseModel):
    id: int
    task_id: int
    title: str
    status: TaskStatus
    assignee: UserOut | None
    due_date: date | None


class TaskOut(BaseModel):
    """A task as listed. ``subtasks_done``/``subtasks_total`` give its progress."""

    id: int
    project_id: int
    title: str
    description: str | None
    status: TaskStatus
    assignee: UserOut | None
    due_date: date | None
    created_at: datetime
    completed_at: datetime | None
    subtasks_done: int
    subtasks_total: int


class TaskDetail(TaskOut):
    """A single task with its subtasks spelled out."""

    subtasks: list[SubtaskOut]


def to_subtask_out(subtask: "Subtask") -> SubtaskOut:
    return SubtaskOut(
        id=subtask.id,
        task_id=subtask.task_id,
        title=subtask.title,
        status=TaskStatus(subtask.status),
        assignee=to_user_out(subtask.assignee) if subtask.assignee else None,
        due_date=subtask.due_date,
    )


def _task_fields(task: "Task") -> dict:
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "status": TaskStatus(task.status),
        "assignee": to_user_out(task.assignee) if task.assignee else None,
        "due_date": task.due_date,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "subtasks_done": sum(1 for s in task.subtasks if s.status == TaskStatus.DONE),
        "subtasks_total": len(task.subtasks),
    }


def to_task_out(task: "Task") -> TaskOut:
    return TaskOut(**_task_fields(task))


def to_task_detail(task: "Task") -> TaskDetail:
    return TaskDetail(
        **_task_fields(task),
        subtasks=[to_subtask_out(subtask) for subtask in task.subtasks],
    )
