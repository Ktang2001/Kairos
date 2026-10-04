"""Saving and reading the test messages (the ``messages`` table)."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.message import Message


def create_message(db: Session, sender: str, content: str) -> Message:
    """Save one message and return it with its new id and time."""
    message = Message(sender=sender, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_recent_messages(db: Session, limit: int = 50) -> list[Message]:
    """The newest ``limit`` messages, newest first."""
    stmt = select(Message).order_by(Message.id.desc()).limit(limit)
    return list(db.scalars(stmt))


# TODO(attachments): store uploaded files here, e.g.
#   def create_attachment_message(db, *, sender, content, kind, filename, data) -> Message
# Save the bytes outside the database (e.g. a folder next to kairos.db, which
# must then be added to .gitignore) under a server-generated name -- never the
# uploaded filename, which could contain "../" -- and record the original name,
# kind, size and stored path on the Message (see server/models/message.py).
