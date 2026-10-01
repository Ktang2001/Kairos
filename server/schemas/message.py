from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

# Defined in shared/ so the client's message box uses the same limits;
# re-exported here because server code and tests import them from this module.
from shared.message_rules import MAX_CONTENT_LENGTH, MAX_SENDER_LENGTH

__all__ = ["MAX_CONTENT_LENGTH", "MAX_SENDER_LENGTH", "MessageCreate", "MessageOut"]


class MessageCreate(BaseModel):
    """Payload a client sends to POST /messages.

    There is no ``sender`` field: the server uses the signed-in user's name,
    so nobody can post as someone else. A ``sender`` sent anyway is ignored.

    Whitespace is stripped before the length checks, so "   " counts as empty
    and is rejected.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=MAX_CONTENT_LENGTH)


class MessageOut(BaseModel):
    """A persisted message, returned as confirmation."""

    id: int
    sender: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}
