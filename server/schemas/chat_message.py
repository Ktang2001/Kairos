from datetime import datetime

from pydantic import BaseModel, Field

from server.schemas.attachment import AttachmentOut


class ChatMessageCreate(BaseModel):
    body: str | None = None
    client_token: str | None = None


class ChatMessageOut(BaseModel):
    id: int
    conversation_id: int
    sender_user_id: int
    body: str | None
    client_token: str | None
    created_at: datetime
    attachments: list[AttachmentOut] = Field(default_factory=list)
    #: Set when this message announces a meeting; the client fetches the
    #: meeting itself (GET /conversations/{id}/meetings), since replies change
    #: after the message is sent and what each viewer sees differs.
    meeting_id: int | None = None

    model_config = {"from_attributes": True}
