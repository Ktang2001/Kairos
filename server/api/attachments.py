from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from server.api.dependencies import get_current_user_id
from server.db.session import get_db
from server.models.attachment import Attachment
from server.realtime.connection_manager import manager
from server.schemas.chat_message import ChatMessageOut
from server.services import attachment_service, conversation_service
from server.services.attachment_service import UploadTooLargeError
from server.services.conversation_service import NotParticipantError

router = APIRouter(tags=["attachments"])


@router.post("/conversations/{conversation_id}/attachments", response_model=ChatMessageOut)
async def upload_attachment(
    conversation_id: int,
    file: UploadFile = File(...),  # noqa: B008
    caption: str | None = Form(None),
    client_token: str | None = Form(None),
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> ChatMessageOut:
    """No type restriction on the uploaded file - video/audio/documents/anything, per spec."""
    try:
        conversation_service.require_participant(db, conversation_id, current_user_id)
    except NotParticipantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        message = attachment_service.save_attachment(
            db,
            conversation_id,
            uploaded_by_user_id=current_user_id,
            upload=file,
            caption=caption,
            client_token=client_token,
        )
    except UploadTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc

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


@router.get("/attachments/{attachment_id}/download")
def download_attachment(
    attachment_id: int,
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> FileResponse:
    attachment = db.get(Attachment, attachment_id)
    if attachment is None:
        raise HTTPException(status_code=404, detail="Attachment not found")

    try:
        conversation_service.require_participant(
            db, attachment.chat_message.conversation_id, current_user_id
        )
    except NotParticipantError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    path = attachment_service.resolve_download_path(db, attachment)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Attachment file is missing on disk")

    return FileResponse(
        path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
    )
