"""Request and response shapes for the project routes."""

from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from shared.statuses import ProjectStatus, TaskStatus
from shared.text_rules import clean_display_text

if TYPE_CHECKING:
    from server.models.project import Project
    from server.models.task import Task

MAX_PROJECT_NAME_LENGTH = 100
MAX_PROJECT_DESCRIPTION_LENGTH = 2000

#: Invisible/control characters stripped before the length check.
CleanText = Annotated[str, BeforeValidator(clean_display_text)]


class ProjectCreate(BaseModel):
    """Body of POST /teams/{team_id}/projects. New projects start ``active``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: CleanText = Field(min_length=1, max_length=MAX_PROJECT_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_PROJECT_DESCRIPTION_LENGTH)


class ProjectUpdate(BaseModel):
    """Body of PATCH /projects/{id}. Only the fields sent are changed.

    ``description`` may be sent as null to clear it; ``name`` and ``status``
    may not, since a project always has both.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    name: CleanText | None = Field(default=None, min_length=1, max_length=MAX_PROJECT_NAME_LENGTH)
    description: str | None = Field(default=None, max_length=MAX_PROJECT_DESCRIPTION_LENGTH)
    status: ProjectStatus | None = None

    @model_validator(mode="after")
    def required_fields_are_not_null(self) -> "ProjectUpdate":
        for field in ("name", "status"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class StatusCounts(BaseModel):
    """How many tasks are in each status. Also used by the dashboard."""

    todo: int = 0
    in_progress: int = 0
    done: int = 0
    total: int = 0


class ProjectOut(BaseModel):
    id: int
    team_id: int
    name: str
    description: str | None
    status: ProjectStatus
    created_at: datetime
    tasks: StatusCounts


def count_statuses(tasks: Iterable["Task"]) -> StatusCounts:
    counts = StatusCounts()
    for task in tasks:
        if task.status == TaskStatus.TODO:
            counts.todo += 1
        elif task.status == TaskStatus.IN_PROGRESS:
            counts.in_progress += 1
        elif task.status == TaskStatus.DONE:
            counts.done += 1
        counts.total += 1
    return counts


def to_project_out(project: "Project") -> ProjectOut:
    return ProjectOut(
        id=project.id,
        team_id=project.team_id,
        name=project.name,
        description=project.description,
        status=ProjectStatus(project.status),
        created_at=project.created_at,
        tasks=count_statuses(project.tasks),
    )
