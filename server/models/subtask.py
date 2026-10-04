"""The ``subtasks`` table (unused for now, see below)."""

from datetime import date

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class Subtask(Base):
    """A step inside a task. Not used by the API yet: projects, tasks and subtasks (context.md goals
    4-7) were taken out of the app for now. The table stays so the database matches the migrations.
    """

    __tablename__ = "subtasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str]
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    due_date: Mapped[date | None]
    status: Mapped[str]
