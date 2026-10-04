from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.api.dependencies import get_current_user_id
from server.db.session import get_db
from server.realtime.connection_manager import manager
from server.schemas.conversation import (
    ConversationOut,
    DirectConversationCreate,
    GroupConversationCreate,
    ParticipantAdd,
    ParticipantRoleUpdate,
)
from server.services import conversation_service
from server.services.conversation_service import (
    LastAdminError,
    NotConversationAdminError,
    NotParticipantError,
)

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_my_conversations(
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> list[ConversationOut]:
    conversations = conversation_service.list_conversations_for_user(db, current_user_id)
    return [ConversationOut.model_validate(c) for c in conversations]


async def _broadcast_conversation_event(
    db: Session, conversation_id: int, event_type: str, **extra
) -> None:
    participant_ids = conversation_service.list_participant_user_ids(db, conversation_id)
    await manager.broadcast_to_users(
        participant_ids, {"type": event_type, "conversation_id": conversation_id, **extra}
    )


@router.post("/direct", response_model=ConversationOut)
async def start_direct_conversation(
    payload: DirectConversationCreate,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ConversationOut:
    try:
        conversation, created = conversation_service.get_or_create_direct_conversation(
            db, current_user_id, payload.other_user_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out = ConversationOut.model_validate(conversation)
    if created:
        await _broadcast_conversation_event(
            db, conversation.id, "conversation_created", conversation=out.model_dump(mode="json")
        )
    return out


@router.post("/group", response_model=ConversationOut)
async def create_group_conversation(
    payload: GroupConversationCreate,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ConversationOut:
    conversation = conversation_service.create_group_conversation(
        db, current_user_id, name=payload.name, member_user_ids=payload.member_user_ids
    )

    out = ConversationOut.model_validate(conversation)
    await _broadcast_conversation_event(
        db, conversation.id, "conversation_created", conversation=out.model_dump(mode="json")
    )
    return out


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(
    conversation_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ConversationOut:
    try:
        conversation_service.require_participant(db, conversation_id, current_user_id)
    except NotParticipantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    conversation = conversation_service.get_conversation(db, conversation_id)
    return ConversationOut.model_validate(conversation)


@router.post("/{conversation_id}/participants", response_model=ConversationOut)
async def add_participant(
    conversation_id: int,
    payload: ParticipantAdd,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ConversationOut:
    try:
        conversation = conversation_service.add_participant(
            db,
            conversation_id,
            acting_user_id=current_user_id,
            new_user_id=payload.user_id,
            role=payload.role,
        )
    except (NotParticipantError, NotConversationAdminError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _broadcast_conversation_event(
        db, conversation_id, "participant_added", user_id=payload.user_id, role=payload.role
    )
    return ConversationOut.model_validate(conversation)


@router.delete("/{conversation_id}/participants/{user_id}", response_model=ConversationOut)
async def remove_participant(
    conversation_id: int,
    user_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ConversationOut:
    # Captured before removal so the removed user (no longer a participant
    # afterwards) still gets notified that they were removed.
    pre_removal_participant_ids = conversation_service.list_participant_user_ids(
        db, conversation_id
    )
    try:
        conversation = conversation_service.remove_participant(
            db, conversation_id, acting_user_id=current_user_id, target_user_id=user_id
        )
    except (NotParticipantError, NotConversationAdminError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    await manager.broadcast_to_users(
        pre_removal_participant_ids,
        {"type": "participant_removed", "conversation_id": conversation_id, "user_id": user_id},
    )
    return ConversationOut.model_validate(conversation)


@router.put("/{conversation_id}/participants/{user_id}/role", response_model=ConversationOut)
async def update_participant_role(
    conversation_id: int,
    user_id: int,
    payload: ParticipantRoleUpdate,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ConversationOut:
    try:
        conversation = conversation_service.change_participant_role(
            db,
            conversation_id,
            acting_user_id=current_user_id,
            target_user_id=user_id,
            new_role=payload.role,
        )
    except (NotParticipantError, NotConversationAdminError) as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except LastAdminError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await _broadcast_conversation_event(
        db,
        conversation_id,
        "participant_role_changed",
        user_id=user_id,
        role=payload.role,
    )
    return ConversationOut.model_validate(conversation)
