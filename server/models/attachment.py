from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base


class Attachment(Base):
    """A file attached to a chat message, stored on disk under the server's configured upload root.

    `original_filename` is display-only and must never be used to build a filesystem
    path - `stored_filename` is a server-generated name, which is what actually gets
    written to disk (see server/services/attachment_service.py).
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    original_filename: Mapped[str]
    stored_filename: Mapped[str] = mapped_column(unique=True)
    content_type: Mapped[str | None]
    size_bytes: Mapped[int]
    uploaded_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )

    chat_message: Mapped["ChatMessage"] = relationship(back_populates="attachments")  # noqa: F821
