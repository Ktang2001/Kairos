"""Meetings: Jitsi calls started or scheduled from a chat or a team.

Every meeting lives in a conversation -- a team's chat for a team meeting --
and is announced there by one chat message (``chat_message_id``), which the
client shows as the meeting's card. Who is invited is whoever is in that
conversation; for a team chat that follows the team's members, and admins can
also see it (server/services/meeting_service.py).
"""

from datetime import datetime, timedelta

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from server.models.base import Base
from server.models.chat_message import ChatMessage
from server.models.conversation import Conversation
from server.models.encrypted_text import EncryptedText
from server.models.user import User


class Meeting(Base):
    """One Jitsi meeting: its host, when it is, and the room it uses."""

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id"), index=True)
    #: The message that announced it in the chat (the card the client shows).
    chat_message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), unique=True)
    #: Whoever created it. Only they (or an admin) can cancel it.
    host_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    #: Encrypted at rest, like the chat message that announces it.
    title: Mapped[str] = mapped_column(EncryptedText(), nullable=False)
    #: Naive UTC, like every other stored time.
    starts_at: Mapped[datetime] = mapped_column(DateTime(), index=True)
    duration_minutes: Mapped[int]
    #: The Jitsi room. Random and unguessable: a public Jitsi room has no
    #: access control of its own, so anyone who knows the name can join.
    room_name: Mapped[str] = mapped_column(unique=True)
    #: The Jitsi server's address when the meeting was made. Kept per meeting
    #: so changing the server setting later doesn't break links already sent.
    jitsi_base_url: Mapped[str]
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime())
    cancelled_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )

    conversation: Mapped[Conversation] = relationship()
    chat_message: Mapped[ChatMessage] = relationship(back_populates="meeting")
    host: Mapped[User] = relationship(foreign_keys=[host_user_id])
    rsvps: Mapped[list["MeetingRsvp"]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", order_by="MeetingRsvp.user_id"
    )

    @property
    def ends_at(self) -> datetime:
        """When the meeting is over (naive UTC)."""
        return self.starts_at + timedelta(minutes=self.duration_minutes)

    @property
    def join_url(self) -> str:
        """The Jitsi link for this meeting's room."""
        return f"{self.jitsi_base_url}/{self.room_name}"


class MeetingRsvp(Base):
    """One invitee's reply to a meeting: accepted, tentative or declined."""

    __tablename__ = "meeting_rsvps"

    meeting_id: Mapped[int] = mapped_column(ForeignKey("meetings.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    response: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    meeting: Mapped[Meeting] = relationship(back_populates="rsvps")
    user: Mapped[User] = relationship()
