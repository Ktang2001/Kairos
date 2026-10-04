from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session, sessionmaker

from server.api.dependencies import resolve_ws_user_id
from server.db.session import get_session_factory
from server.realtime.connection_manager import manager

router = APIRouter(tags=["realtime"])


@router.websocket("/ws/chat")
async def chat_websocket(
    websocket: WebSocket,
    user_id: int,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),  # noqa: B008
) -> None:
    """Push-only notification channel for an already-identified user.

    All writes go through REST (see server/services/chat_service.py's cursor
    primitive); this socket only tells already-connected clients "something
    changed, here it is". Opens and closes its own short-lived session via
    `session_factory()` rather than depending on `get_db` directly, which is
    request-scoped and would otherwise stay open for the socket's whole lifetime -
    mirrors the pattern in server/gui.py::_poll_new_messages. The factory
    indirection (rather than importing SessionLocal directly) is what lets tests
    override it the same way they override `get_db`.
    """
    db = session_factory()
    try:
        resolved_user_id = resolve_ws_user_id(db, user_id)
    finally:
        db.close()

    if resolved_user_id is None:
        await websocket.close(code=4401)
        return

    await manager.connect(resolved_user_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(resolved_user_id, websocket)
