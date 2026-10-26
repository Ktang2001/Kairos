"""Request and response shapes for the task and subtask routes.

On the PATCH bodies, a field that is *left out* is not changed, while a field
sent as ``null`` is cleared. That is how a client unassigns a task or removes
its dates. Fields a task cannot be without (title, status) refuse null.

``start_date`` must not be after ``due_date``. The create bodies check it here;
on a PATCH only one of the two may be sent, so ``task_service`` checks it
against the stored other end.
"""

from datetime import date, datetime
from typing import TYPE_CHECKING, Annotated, ClassVar

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from server.schemas.user import UserOut, to_user_out
from shared.date_rules import DATE_RANGE_MESSAGE, date_in_range
from shared.statuses import TaskStatus
from shared.text_rules import clean_display_text

if TYPE_CHECKING:
    from server.models.subtask import Subtask
    from server.models.task import Task

MAX_TITLE_LENGTH = 200
MAX_TASK_DESCRIPTION_LENGTH = 5000


def _blank_to_none(value: str | None) -> str | None:
    """Treat an empty description (after whitespace stripping) as no description."""
    return value or None


#: A title with invisible and control characters removed first (zero-width
#: spaces, NUL, right-to-left overrides), so a title can't look blank or
#: reversed on screen. Found by stress testing: "​" was a valid title.
Title = Annotated[str, BeforeValidator(clean_display_text)]

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
        """Refuse ``"title": null`` and ``"status": null``: a task always has both."""
        for field in self._required:
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class _DatesInOrder(BaseModel):
    """Rejects a body whose ``start_date`` is after its ``due_date``."""

    start_date: date | None = None
    due_date: date | None = None

    @model_validator(mode="after")
    def start_is_not_after_due(self) -> "_DatesInOrder":
        """Both dates in the allowed range (shared/date_rules.py), and a bar cannot end
        before it starts."""
        if not (date_in_range(self.start_date) and date_in_range(self.due_date)):
            raise ValueError(DATE_RANGE_MESSAGE)
        if self.start_date and self.due_date and self.start_date > self.due_date:
            raise ValueError("start_date cannot be after due_date")
        return self


class TaskCreate(_DatesInOrder):
    """Body of POST /projects/{project_id}/tasks."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Title = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Description = None
    assignee_id: int | None = None
    status: TaskStatus = TaskStatus.TODO


class TaskUpdate(_NoNullRequiredFields, _DatesInOrder):
    """Body of PATCH /tasks/{id}. Only the fields sent are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Title | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    description: Description = None
    assignee_id: int | None = None
    status: TaskStatus | None = None


class SubtaskCreate(_DatesInOrder):
    """Body of POST /tasks/{task_id}/subtasks."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Title = Field(min_length=1, max_length=MAX_TITLE_LENGTH)
    assignee_id: int | None = None
    status: TaskStatus = TaskStatus.TODO


class SubtaskUpdate(_NoNullRequiredFields, _DatesInOrder):
    """Body of PATCH /subtasks/{id}. Only the fields sent are changed."""

    model_config = ConfigDict(str_strip_whitespace=True)

    title: Title | None = Field(default=None, min_length=1, max_length=MAX_TITLE_LENGTH)
    assignee_id: int | None = None
    status: TaskStatus | None = None


class DependencyIn(BaseModel):
    """Body of POST /tasks/{id}/dependencies: the task that must finish first."""

    depends_on_id: int


class SubtaskOut(BaseModel):
    """A subtask as shown inside its parent task."""

    id: int
    task_id: int
    title: str
    status: TaskStatus
    assignee: UserOut | None
    start_date: date | None
    due_date: date | None


class TaskOut(BaseModel):
    """A task as listed. ``subtasks_done``/``subtasks_total`` give its progress;
    ``depends_on`` lists the ids of the tasks that must finish first.
    """

    id: int
    project_id: int
    title: str
    description: str | None
    status: TaskStatus
    assignee: UserOut | None
    start_date: date | None
    due_date: date | None
    created_at: datetime
    completed_at: datetime | None
    subtasks_done: int
    subtasks_total: int
    depends_on: list[int]
    #: Who holds this task's subtasks (no repeats, lowest id first), so a list of
    #: tasks can show someone the work assigned to them inside other people's tasks.
    subtask_assignee_ids: list[int]


class TaskDetail(TaskOut):
    """A single task with its subtasks spelled out."""

    subtasks: list[SubtaskOut]


def to_subtask_out(subtask: "Subtask") -> SubtaskOut:
    """Flatten an ORM ``Subtask`` for the client."""
    return SubtaskOut(
        id=subtask.id,
        task_id=subtask.task_id,
        title=subtask.title,
        status=TaskStatus(subtask.status),
        assignee=to_user_out(subtask.assignee) if subtask.assignee else None,
        start_date=subtask.start_date,
        due_date=subtask.due_date,
    )


def _task_fields(task: "Task") -> dict:
    """The fields ``TaskOut`` and ``TaskDetail`` share."""
    return {
        "id": task.id,
        "project_id": task.project_id,
        "title": task.title,
        "description": task.description,
        "status": TaskStatus(task.status),
        "assignee": to_user_out(task.assignee) if task.assignee else None,
        "start_date": task.start_date,
        "due_date": task.due_date,
        "created_at": task.created_at,
        "completed_at": task.completed_at,
        "subtasks_done": sum(1 for s in task.subtasks if s.status == TaskStatus.DONE),
        "subtasks_total": len(task.subtasks),
        "depends_on": [other.id for other in task.depends_on],
        "subtask_assignee_ids": sorted({s.assignee_id for s in task.subtasks if s.assignee_id}),
    }


def to_task_out(task: "Task") -> TaskOut:
    """Flatten an ORM ``Task`` for a list response."""
    return TaskOut(**_task_fields(task))


def to_task_detail(task: "Task") -> TaskDetail:
    """Flatten an ORM ``Task`` with its subtasks for a single-task response."""
    return TaskDetail(
        **_task_fields(task),
        subtasks=[to_subtask_out(subtask) for subtask in task.subtasks],
    )
