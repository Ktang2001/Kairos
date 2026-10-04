"""The connectivity-test messages.

Both routes require a signed-in user, and the sender is always the signed-in
user's name, set here on the server. (They used to be open, which let anyone
on the network read every message and post under any name, e.g. "Admin".)
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from server.api.deps import get_current_user
from server.db.session import get_db
from server.models.user import User
from server.schemas.message import MessageCreate, MessageOut
from server.services import message_service

#: Upper bound on GET /messages?limit=. Without it, limit=-1 (which SQLite
#: reads as "no limit") or a huge number returns the whole table.
MAX_MESSAGES_PER_REQUEST = 200

router = APIRouter()


@router.post("/messages", response_model=MessageOut)
def send_message(
    payload: MessageCreate,
    db: Session = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> MessageOut:
    message = message_service.create_message(db, sender=current_user.name, content=payload.content)
    return MessageOut.model_validate(message)


# TODO(attachments): add the upload route here, e.g.
#   @router.post("/messages/attachments", response_model=MessageOut)
#   def send_attachment(file: UploadFile, kind: str = Form(...), content: str = Form(""),
#                       db=Depends(get_db), current_user=Depends(get_current_user)): ...
# Require login like send_message, take the sender from current_user (never from
# the request), check kind/size/type, then hand off to message_service. FastAPI
# needs the "python-multipart" package for UploadFile/Form -- a new dependency,
# so flag it to the team first (context.md section 7).


@router.get("/messages", response_model=list[MessageOut])
def get_messages(
    limit: int = Query(50, ge=1, le=MAX_MESSAGES_PER_REQUEST),
    db: Session = Depends(get_db),  # noqa: B008
    _user: User = Depends(get_current_user),  # noqa: B008
) -> list[MessageOut]:
    messages = message_service.list_recent_messages(db, limit=limit)
    return [MessageOut.model_validate(m) for m in messages]
