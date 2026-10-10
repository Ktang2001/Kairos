from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from server.models.conversation import Conversation, ConversationParticipant
from shared.chat_enums import ConversationKind, ParticipantRole


class ConversationError(Exception):
    """Base class for conversation-service errors; the API layer translates these to HTTP responses."""


class NotParticipantError(ConversationError):
    """Raised when the acting user is not a member of the conversation."""


class NotConversationAdminError(ConversationError):
    """Raised when the acting user is a member but not an admin of the conversation."""


class LastAdminError(ConversationError):
    """Raised when an operation would leave a group chat with zero admins."""


def _with_participants(stmt):
    return stmt.options(selectinload(Conversation.participants))


def get_conversation(db: Session, conversation_id: int) -> Conversation | None:
    stmt = _with_participants(select(Conversation).where(Conversation.id == conversation_id))
    return db.scalars(stmt).first()


def require_participant(db: Session, conversation_id: int, user_id: int) -> ConversationParticipant:
    participant = db.get(ConversationParticipant, (conversation_id, user_id))
    if participant is None:
        raise NotParticipantError(f"user {user_id} is not in conversation {conversation_id}")
    return participant


def require_conversation_admin(
    db: Session, conversation_id: int, user_id: int
) -> ConversationParticipant:
    participant = require_participant(db, conversation_id, user_id)
    if participant.role != ParticipantRole.ADMIN.value:
        raise NotConversationAdminError(
            f"user {user_id} is not an admin of conversation {conversation_id}"
        )
    return participant


def list_participant_user_ids(db: Session, conversation_id: int) -> list[int]:
    """Who should be notified over the WebSocket about a change to this conversation."""
    conversation = get_conversation(db, conversation_id)
    if conversation is None:
        return []
    return [p.user_id for p in conversation.participants]


def list_conversations_for_user(db: Session, user_id: int) -> list[Conversation]:
    stmt = _with_participants(
        select(Conversation)
        .join(ConversationParticipant)
        .where(ConversationParticipant.user_id == user_id)
        .order_by(Conversation.created_at.desc())
    )
    return list(db.scalars(stmt))


def get_or_create_direct_conversation(
    db: Session, user_id: int, other_user_id: int
) -> tuple[Conversation, bool]:
    """Reuse the existing 1:1 thread between these two users if one exists, else create it.

    Returns `(conversation, created)` so callers (e.g. the "conversation_created"
    WebSocket broadcast) can tell a fresh thread apart from a repeat "start chat"
    click, which should not re-notify the other party.
    """
    if user_id == other_user_id:
        raise ValueError("cannot start a direct conversation with yourself")

    for conversation in list_conversations_for_user(db, user_id):
        if conversation.kind != ConversationKind.DIRECT.value:
            continue
        participant_ids = {p.user_id for p in conversation.participants}
        if participant_ids == {user_id, other_user_id}:
            return conversation, False

    conversation = Conversation(
        kind=ConversationKind.DIRECT.value, name=None, created_by_user_id=user_id
    )
    db.add(conversation)
    db.flush()
    db.add_all(
        [
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_id,
                role=ParticipantRole.MEMBER.value,
            ),
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=other_user_id,
                role=ParticipantRole.MEMBER.value,
            ),
        ]
    )
    db.commit()
    db.refresh(conversation)
    return get_conversation(db, conversation.id), True


def create_group_conversation(
    db: Session, creator_user_id: int, name: str, member_user_ids: list[int]
) -> Conversation:
    """Create a group chat. The creator is always the group's (first) admin."""
    member_ids = {uid for uid in member_user_ids if uid != creator_user_id}

    conversation = Conversation(
        kind=ConversationKind.GROUP.value, name=name, created_by_user_id=creator_user_id
    )
    db.add(conversation)
    db.flush()

    participants = [
        ConversationParticipant(
            conversation_id=conversation.id,
            user_id=creator_user_id,
            role=ParticipantRole.ADMIN.value,
        )
    ]
    participants += [
        ConversationParticipant(
            conversation_id=conversation.id, user_id=uid, role=ParticipantRole.MEMBER.value
        )
        for uid in member_ids
    ]
    db.add_all(participants)
    db.commit()
    return get_conversation(db, conversation.id)


def add_participant(
    db: Session, conversation_id: int, acting_user_id: int, new_user_id: int, role: str
) -> Conversation:
    conversation = get_conversation(db, conversation_id)
    if conversation is None:
        raise NotParticipantError(f"conversation {conversation_id} does not exist")
    require_conversation_admin(db, conversation_id, acting_user_id)
    if conversation.kind != ConversationKind.GROUP.value:
        raise ValueError("cannot add participants to a direct conversation")
    if db.get(ConversationParticipant, (conversation_id, new_user_id)) is not None:
        raise ValueError(f"user {new_user_id} is already in conversation {conversation_id}")

    db.add(ConversationParticipant(conversation_id=conversation_id, user_id=new_user_id, role=role))
    db.commit()
    return get_conversation(db, conversation_id)


def _count_admins(conversation: Conversation) -> int:
    return sum(1 for p in conversation.participants if p.role == ParticipantRole.ADMIN.value)


def remove_participant(
    db: Session, conversation_id: int, acting_user_id: int, target_user_id: int
) -> Conversation:
    """Remove `target_user_id`, or leave the conversation when it's the acting
    user's own id - that self-removal is the one case that doesn't require
    being an admin (mirrors teams' remove_member; see client.py)."""
    conversation = get_conversation(db, conversation_id)
    if conversation is None:
        raise NotParticipantError(f"conversation {conversation_id} does not exist")
    target = require_participant(db, conversation_id, target_user_id)
    if acting_user_id != target_user_id:
        require_conversation_admin(db, conversation_id, acting_user_id)

    if target.role == ParticipantRole.ADMIN.value and _count_admins(conversation) <= 1:
        raise LastAdminError("cannot remove the last admin of a conversation")

    db.delete(target)
    db.commit()
    return get_conversation(db, conversation_id)


def change_participant_role(
    db: Session, conversation_id: int, acting_user_id: int, target_user_id: int, new_role: str
) -> Conversation:
    if new_role not in (ParticipantRole.ADMIN.value, ParticipantRole.MEMBER.value):
        raise ValueError(f"invalid role: {new_role}")

    conversation = get_conversation(db, conversation_id)
    if conversation is None:
        raise NotParticipantError(f"conversation {conversation_id} does not exist")
    require_conversation_admin(db, conversation_id, acting_user_id)
    target = require_participant(db, conversation_id, target_user_id)

    if (
        target.role == ParticipantRole.ADMIN.value
        and new_role == ParticipantRole.MEMBER.value
        and _count_admins(conversation) <= 1
    ):
        raise LastAdminError("cannot demote the last admin of a conversation")

    target.role = new_role
    db.commit()
    return get_conversation(db, conversation_id)
