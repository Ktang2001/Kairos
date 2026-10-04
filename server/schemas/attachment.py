from datetime import datetime

from pydantic import BaseModel


class AttachmentOut(BaseModel):
    """`stored_filename` is intentionally not exposed - downloads go through the
    attachment id (see server/api/attachments.py), never the on-disk name.
    """

    id: int
    chat_message_id: int
    original_filename: str
    content_type: str | None
    size_bytes: int
    uploaded_by_user_id: int
    created_at: datetime

    model_config = {"from_attributes": True}
