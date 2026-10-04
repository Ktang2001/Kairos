"""The ``projects`` table (unused for now, see below)."""

from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from server.models.base import Base


class Project(Base):
    """A project belonging to a team. Not used by the API yet: projects, tasks and subtasks
    (context.md goals 4-7) were taken out of the app for now. The table stays so the database
    matches the migrations. Deleting a team checks it (``TeamHasProjects``).
    """

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    name: Mapped[str]
    description: Mapped[str | None]
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
