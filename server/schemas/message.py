from datetime import datetime

from pydantic import BaseModel


class MessageCreate(BaseModel):
    """Payload a client sends to POST /messages."""

    sender: str
    content: str


class MessageOut(BaseModel):
    """A persisted message, returned as confirmation."""

    id: int
    sender: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
