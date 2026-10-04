from datetime import datetime

from pydantic import BaseModel, Field

from shared.chat_enums import ParticipantRole


class ParticipantOut(BaseModel):
    user_id: int
    role: str
    joined_at: datetime

    model_config = {"from_attributes": True}


class ConversationOut(BaseModel):
    id: int
    kind: str
    name: str | None
    created_by_user_id: int
    created_at: datetime
    participants: list[ParticipantOut] = Field(default_factory=list)

    model_config = {"from_attributes": True}


class DirectConversationCreate(BaseModel):
    """Start (or reuse) a 1:1 conversation with another user."""

    other_user_id: int


class GroupConversationCreate(BaseModel):
    """Create a new group chat. The creator is auto-added as the group's admin."""

    name: str
    member_user_ids: list[int] = Field(default_factory=list)


class ParticipantAdd(BaseModel):
    user_id: int
    role: str = ParticipantRole.MEMBER.value


class ParticipantRoleUpdate(BaseModel):
    role: str
