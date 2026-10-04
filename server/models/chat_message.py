from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base


class ChatMessage(Base):
    """A message sent in a conversation.

    Distinct from the legacy `Message` model (server/models/message.py), which is a
    flat connectivity smoke-test ping and is not part of the real chat feature.
    """

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    sender_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str | None]
    client_token: Mapped[str | None] = mapped_column(unique=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False, index=True
    )

    attachments: Mapped[list["Attachment"]] = relationship(  # noqa: F821
        back_populates="chat_message"
    )
