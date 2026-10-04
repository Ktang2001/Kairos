from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.api.dependencies import require_global_admin
from server.db.session import get_db
from server.realtime.connection_manager import manager
from server.schemas.server_settings import ServerInfoPublic, ServerSettingsUpdate
from server.services import server_settings_service

router = APIRouter(prefix="/server", tags=["server-settings"])


@router.get("/info", response_model=ServerInfoPublic)
def get_server_info(db: Session = Depends(get_db)) -> ServerInfoPublic:  # noqa: B008
    """Public - any client can fetch the server's self-reported display name."""
    settings = server_settings_service.get_settings(db)
    return ServerInfoPublic.model_validate(settings)


@router.put("/info", response_model=ServerInfoPublic)
async def update_server_info(
    payload: ServerSettingsUpdate,
    _admin_user_id: int = Depends(require_global_admin),
    db: Session = Depends(get_db),  # noqa: B008
) -> ServerInfoPublic:
    """Gated by the site-wide global-admin Role (see server/api/dependencies.py) -
    distinct from the per-conversation ParticipantRole used for group chats.

    Only this remote path broadcasts `server_info_updated` live - the host's own
    in-process save in server/gui.py runs on a different thread than the uvicorn
    event loop that owns these WebSocket connections, so a connected client's view
    of a locally-made change only catches up next time it fetches GET /server/info.
    """
    try:
        settings = server_settings_service.update_settings(
            db,
            display_name=payload.display_name,
            upload_root=payload.upload_root,
            max_upload_size_bytes=payload.max_upload_size_bytes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    out = ServerInfoPublic.model_validate(settings)
    await manager.broadcast_to_all({"type": "server_info_updated", **out.model_dump(mode="json")})
    return out
