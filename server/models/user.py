"""The ``users`` table: one row per account."""

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base


class User(Base):
    """An account. ``email`` is unique and stored lower-case; ``password_hash`` is an scrypt hash
    (see server/services/password_service.py), never the password; ``role`` is admin, project_lead
    or member.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))

    role: Mapped["Role"] = relationship()  # noqa: F821

    #: Login sessions for this user. ``delete-orphan`` means deleting a user
    #: through the ORM also removes their sessions; SQLite does not enforce
    #: the ``sessions.user_id`` foreign key unless PRAGMA foreign_keys=ON,
    #: so the ORM cascade is what actually performs this cleanup.
    sessions: Mapped[list["Session"]] = relationship(  # noqa: F821
        back_populates="user", cascade="all, delete-orphan"
    )
