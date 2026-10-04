from sqlalchemy import select
from sqlalchemy.orm import Session

from server.models.chat_message import ChatMessage


def create_message(
    db: Session,
    conversation_id: int,
    sender_user_id: int,
    body: str,
    client_token: str | None = None,
) -> ChatMessage:
    """Persist a text chat message.

    Idempotent on `client_token`: resending the same token (e.g. an offline-outbox
    retry after a dropped response) returns the existing message instead of creating
    a duplicate.
    """
    body = body.strip()
    if not body:
        raise ValueError("message body cannot be empty")

    if client_token:
        existing = db.scalars(
            select(ChatMessage).where(ChatMessage.client_token == client_token)
        ).first()
        if existing is not None:
            return existing

    message = ChatMessage(
        conversation_id=conversation_id,
        sender_user_id=sender_user_id,
        body=body,
        client_token=client_token,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_messages_after(
    db: Session, conversation_id: int, after_id: int = 0, limit: int = 50
) -> list[ChatMessage]:
    """The one cursor primitive: every message in this conversation with id > after_id,
    oldest first, capped at `limit`.

    Used identically for initial history load, polling fallback when the realtime
    WebSocket is down, and offline-reconnect catch-up (see context.md's chat-feature
    data model note) - there is exactly one way to ask "what did I miss".
    """
    stmt = (
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conversation_id)
        .where(ChatMessage.id > after_id)
        .order_by(ChatMessage.id.asc())
        .limit(limit)
    )
    return list(db.scalars(stmt))
