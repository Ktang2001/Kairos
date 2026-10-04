"""Teams and their membership (context.md goal #1).

Roles stay app-wide (admin / project_lead / member, on ``User.role``). The one
team-specific piece of authority is ``Team.lead_id``: the team's lead may
manage that team, alongside any admin. The lead is always also a member.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Table, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base
from server.models.user import User

team_members = Table(
    "team_members",
    Base.metadata,
    Column("team_id", ForeignKey("teams.id"), primary_key=True),
    Column("user_id", ForeignKey("users.id"), primary_key=True),
)


class Team(Base):
    """A named group of users that projects belong to."""

    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)

    #: Stored as the creator typed it (after trimming) for display. Uniqueness
    #: is case-insensitive -- see ``uq_teams_name_lower`` below the class -- so
    #: "Alpha" and "alpha" cannot both exist.
    name: Mapped[str]

    #: The member who manages this team. Indexed because "which teams does this
    #: user lead" is asked whenever a user's permissions are checked.
    lead_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )

    lead: Mapped[User] = relationship(foreign_keys=[lead_id])

    #: Ordered by user id so member lists come back in a stable order.
    members: Mapped[list[User]] = relationship(secondary=team_members, order_by=User.id)


# An expression index: a plain UNIQUE on ``name`` would treat "Alpha" and
# "alpha" as different teams. The service checks first so callers get a clean
# 409; this index is what holds when two requests race. Declared after the class
# because it needs the mapped ``Team.name`` column.
Index("uq_teams_name_lower", func.lower(Team.name), unique=True)
