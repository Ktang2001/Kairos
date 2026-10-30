from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base
from server.models.team import Team
from shared.chat_enums import ParticipantRole


class Conversation(Base):
    """A 1:1 direct chat or a group chat thread."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str]
    name: Mapped[str | None]
    created_by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )

    #: Set for a team's own group chat, whose participants follow the team's
    #: members (server/services/conversation_service.py::sync_team_conversation).
    #: At most one chat per team; None for every other conversation, and again
    #: once the team is deleted (the chat and its history are kept).
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), unique=True)

    team: Mapped[Team | None] = relationship()

    participants: Mapped[list["ConversationParticipant"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class ConversationParticipant(Base):
    """A user's membership in a conversation, carrying their per-conversation role."""

    __tablename__ = "conversation_participants"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(default=ParticipantRole.MEMBER.value)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="participants")
