"""The ``subtasks`` table: smaller steps inside a task."""

from datetime import date

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base


class Subtask(Base):
    """A smaller step inside a task. Uses the same statuses as tasks.

    Shown on the Gantt chart as a row under its task when it has dates.
    """

    __tablename__ = "subtasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    title: Mapped[str]
    #: Must be a member of the team that owns the parent task's project.
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    start_date: Mapped[date | None]
    due_date: Mapped[date | None]
    #: A ``shared.statuses.TaskStatus`` value.
    status: Mapped[str]

    task: Mapped["Task"] = relationship(back_populates="subtasks")  # noqa: F821
    assignee: Mapped["User | None"] = relationship()  # noqa: F821
