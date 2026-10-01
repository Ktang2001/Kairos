"""Server-side login sessions.

A login hands the client an opaque random token. Only the SHA-256 *hash* of
that token is stored here, so a leaked database file does not give an attacker
a usable credential -- the same reasoning as never storing a raw password. The
plaintext token is returned to the client exactly once, at login.

Named ``Session`` after the entity (matching User/Team/Task/...), which means
files that also need SQLAlchemy's ORM ``Session`` have to alias one of them.
The service layer does that in one place and explains why.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base


class Session(Base):
    """One logged-in session belonging to one user."""

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    #: SHA-256 hex digest of the bearer token. Unique because two logins must
    #: never resolve to the same credential, and indexed because every
    #: authenticated request looks a session up by this column.
    token_hash: Mapped[str] = mapped_column(unique=True, index=True)

    #: Stored naive-UTC to match SQLite's CURRENT_TIMESTAMP and to keep
    #: comparisons against ``expires_at`` free of timezone surprises.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)

    #: Set when the user logs out or the session is otherwise retired. Kept
    #: (rather than deleting the row) so expiry and logout are distinguishable.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    user: Mapped["User"] = relationship(back_populates="sessions")  # noqa: F821
