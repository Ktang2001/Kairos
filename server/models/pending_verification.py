from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class PendingVerification(Base):
    """A signup/login that passed its password check but still needs the emailed
    6-digit code entered before a real session is issued (see
    server/services/verification_service.py, server/api/auth.py).

    `token` (not the code itself) is what the client holds between the two
    steps - the code is short and guessable, so the token is what actually
    gates which pending attempt a client can even submit a code against.
    """

    __tablename__ = "pending_verifications"

    token: Mapped[str] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    code_hash: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer(), default=0, server_default="0")
