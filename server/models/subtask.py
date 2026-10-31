"""The ``subtasks`` table: smaller steps inside a task."""

from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey
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
    #: As ``Task.due_date`` and ``Task.due_at``: the day, and the exact moment.
    due_date: Mapped[date | None]
    due_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    #: A ``shared.statuses.TaskStatus`` value.
    status: Mapped[str]
    #: Goes up by one with every saved change; see ``Task.version``.
    version: Mapped[int] = mapped_column(default=1, server_default="1")

    task: Mapped["Task"] = relationship(back_populates="subtasks")  # noqa: F821
    assignee: Mapped["User | None"] = relationship()  # noqa: F821
