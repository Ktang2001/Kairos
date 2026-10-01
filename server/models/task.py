from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from server.models.base import Base


class Task(Base):
    """One piece of work in a project, optionally assigned and with a due date."""

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str]
    description: Mapped[str | None]
    #: Must be a member of the project's team; cleared when they leave it.
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    due_date: Mapped[date | None]
    #: A ``shared.statuses.TaskStatus`` value.
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    #: Naive UTC, set when the status becomes "done" and cleared if the task
    #: is reopened. Lets the dashboard count work finished in the last week.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="tasks")  # noqa: F821
    assignee: Mapped["User | None"] = relationship()  # noqa: F821
    subtasks: Mapped[list["Subtask"]] = relationship(  # noqa: F821
        back_populates="task", cascade="all, delete-orphan", order_by="Subtask.id"
    )
