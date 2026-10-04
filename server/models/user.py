from sqlalchemy import Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    email: Mapped[str] = mapped_column(unique=True)
    password_hash: Mapped[str]
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"))
    # Opt-in, chosen at signup (see client/views/auth_dialog.py) - whether
    # POST /auth/login requires the emailed 2FA code (server/api/auth.py) or
    # issues a session immediately, same as signup always does.
    two_factor_enabled: Mapped[bool] = mapped_column(Boolean(), default=False, server_default="0")

    role: Mapped["Role"] = relationship()  # noqa: F821
