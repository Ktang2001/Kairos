from datetime import datetime

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from server.models.base import Base


class Project(Base):
    """A body of work owned by one team. Holds tasks; see ``shared.statuses``."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    name: Mapped[str]
    description: Mapped[str | None]
    #: A ``shared.statuses.ProjectStatus`` value.
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    team: Mapped["Team"] = relationship()  # noqa: F821

    #: ``delete-orphan``: deleting a project deletes its tasks (and, through
    #: ``Task.subtasks``, their subtasks). SQLite does not enforce foreign
    #: keys here, so without this the tasks would be left pointing at nothing.
    tasks: Mapped[list["Task"]] = relationship(  # noqa: F821
        back_populates="project", cascade="all, delete-orphan", order_by="Task.id"
    )
