from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.message import Message


def create_message(db: Session, sender: str, content: str) -> Message:
    message = Message(sender=sender, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_recent_messages(db: Session, limit: int = 50) -> list[Message]:
    stmt = select(Message).order_by(Message.id.desc()).limit(limit)
    return list(db.scalars(stmt))
