from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.api.dependencies import get_current_user_id
from server.db.session import get_db
from server.realtime.connection_manager import manager
from server.schemas.chat_message import ChatMessageCreate, ChatMessageOut
from server.services import chat_service, conversation_service
from server.services.conversation_service import NotParticipantError

router = APIRouter(prefix="/conversations/{conversation_id}/messages", tags=["chat-messages"])


def _require_participant_or_403(db: Session, conversation_id: int, user_id: int) -> None:
    try:
        conversation_service.require_participant(db, conversation_id, user_id)
    except NotParticipantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("", response_model=list[ChatMessageOut])
def list_messages(
    conversation_id: int,
    after_id: int = 0,
    limit: int = 50,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[ChatMessageOut]:
    """The cursor sync endpoint: `after_id` defaults to 0 for full history."""
    _require_participant_or_403(db, conversation_id, current_user_id)
    messages = chat_service.list_messages_after(db, conversation_id, after_id=after_id, limit=limit)
    return [ChatMessageOut.model_validate(m) for m in messages]


@router.post("", response_model=ChatMessageOut)
async def post_message(
    conversation_id: int,
    payload: ChatMessageCreate,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ChatMessageOut:
    _require_participant_or_403(db, conversation_id, current_user_id)
    try:
        message = chat_service.create_message(
            db,
            conversation_id,
            sender_user_id=current_user_id,
            body=payload.body or "",
            client_token=payload.client_token,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out = ChatMessageOut.model_validate(message)
    participant_ids = conversation_service.list_participant_user_ids(db, conversation_id)
    await manager.broadcast_to_users(
        participant_ids,
        {
            "type": "chat_message",
            "conversation_id": conversation_id,
            "message": out.model_dump(mode="json"),
        },
    )
    return out
