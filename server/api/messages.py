from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.schemas.message import MessageCreate, MessageOut
from server.services import message_service

router = APIRouter()


@router.post("/messages", response_model=MessageOut)
def send_message(payload: MessageCreate, db: Session = Depends(get_db)) -> MessageOut:  # noqa: B008
    message = message_service.create_message(db, sender=payload.sender, content=payload.content)
    return MessageOut.model_validate(message)


@router.get("/messages", response_model=list[MessageOut])
def get_messages(limit: int = 50, db: Session = Depends(get_db)) -> list[MessageOut]:  # noqa: B008
    messages = message_service.list_recent_messages(db, limit=limit)
    return [MessageOut.model_validate(m) for m in messages]
