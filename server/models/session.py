from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class Session(Base):
    """A login session created by signup/login (see server/services/session_service.py).

    `token` (not a surrogate int id) is the primary key - it's the credential itself,
    opaque and unguessable (`secrets.token_urlsafe`), replacing the old placeholder
    where a client-supplied X-Kairos-User-Id header was trusted with no proof at all.
    """

    __tablename__ = "sessions"

    token: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
