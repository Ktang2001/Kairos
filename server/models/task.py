"""The ``tasks`` table and ``task_dependencies``, the links a Gantt chart draws as arrows."""

from datetime import date, datetime

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Table
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from server.models.base import Base

#: "Task ``task_id`` cannot start until task ``depends_on_id`` is finished."
#: Both tasks are in the same project (checked by ``task_service``), and the
#: links never form a loop. Rows go when either task is deleted, through the
#: two relationships below (SQLite does not enforce the foreign keys).
task_dependencies = Table(
    "task_dependencies",
    Base.metadata,
    Column("task_id", ForeignKey("tasks.id"), primary_key=True),
    Column("depends_on_id", ForeignKey("tasks.id"), primary_key=True, index=True),
    CheckConstraint("task_id != depends_on_id", name="ck_task_dependencies_not_self"),
)


class Task(Base):
    """One piece of work in a project, optionally assigned and scheduled.

    ``start_date`` and ``due_date`` are the bar's two ends on the Gantt chart.
    Either may be missing; a task with neither is listed as unscheduled.
    """

    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str]
    description: Mapped[str | None]
    #: Must be a member of the project's team; cleared when they leave it.
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    #: The first day of work. Never after ``due_date`` (checked by the schemas
    #: and ``task_service``).
    start_date: Mapped[date | None]
    #: The calendar day it is due, in the time zone of whoever set it. What
    #: the Gantt chart and the date checks use.
    due_date: Mapped[date | None]
    #: The exact moment it is due (naive UTC): ``due_date`` at the time they
    #: chose, 11:59 PM unless set. What "overdue" is judged by, and what each
    #: person sees converted to their own time zone. Set whenever ``due_date``
    #: is (``task_service``).
    due_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    #: A ``shared.statuses.TaskStatus`` value.
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    #: Goes up by one with every saved change. An edit sends the version it
    #: started from, and is refused if someone else saved in between, instead
    #: of silently overwriting them (``task_service.update_task``).
    version: Mapped[int] = mapped_column(default=1, server_default="1")
    #: Naive UTC, set when the status becomes "done" and cleared if the task
    #: is reopened.
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    project: Mapped["Project"] = relationship(back_populates="tasks")  # noqa: F821
    assignee: Mapped["User | None"] = relationship()  # noqa: F821
    subtasks: Mapped[list["Subtask"]] = relationship(  # noqa: F821
        back_populates="task", cascade="all, delete-orphan", order_by="Subtask.id"
    )

    #: Tasks that must finish before this one starts.
    depends_on: Mapped[list["Task"]] = relationship(
        secondary=task_dependencies,
        primaryjoin=lambda: Task.id == task_dependencies.c.task_id,
        secondaryjoin=lambda: Task.id == task_dependencies.c.depends_on_id,
        back_populates="blocks",
        order_by=lambda: Task.id,
    )
    #: Tasks waiting on this one. The mirror of ``depends_on``; having both
    #: means deleting a task clears its links in both directions.
    blocks: Mapped[list["Task"]] = relationship(
        secondary=task_dependencies,
        primaryjoin=lambda: Task.id == task_dependencies.c.depends_on_id,
        secondaryjoin=lambda: Task.id == task_dependencies.c.task_id,
        back_populates="depends_on",
        order_by=lambda: Task.id,
    )
