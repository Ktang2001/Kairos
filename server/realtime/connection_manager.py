from collections.abc import Iterable
from typing import Any

from fastapi import WebSocket


class ConnectionManager:
    """In-memory registry of open WebSocket connections, keyed by user id.

    The WebSocket is a notification-only layer (see server/api/ws_chat.py) - all
    writes go through REST, so nothing here needs to survive a server restart. A
    single process serves one host's connections (per context.md's architecture
    note, there's no multi-instance scaling concern), so a plain in-memory dict
    is sufficient.
    """

    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = {}

    async def connect(self, user_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.setdefault(user_id, set()).add(websocket)

    def disconnect(self, user_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(user_id)
        if sockets is None:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(user_id, None)

    async def broadcast_to_users(self, user_ids: Iterable[int], event: dict[str, Any]) -> None:
        """Send `event` to every open socket for each of `user_ids`.

        A send failure on one socket (e.g. the client vanished without a clean
        close) is treated as a disconnect rather than aborting the whole broadcast.
        """
        for user_id in user_ids:
            for websocket in list(self._connections.get(user_id, ())):
                try:
                    await websocket.send_json(event)
                except Exception:  # noqa: BLE001 - any send failure means a dead socket
                    self.disconnect(user_id, websocket)

    async def broadcast_to_all(self, event: dict[str, Any]) -> None:
        """Send `event` to every currently-connected user (e.g. a server-wide
        identity/config change, which isn't scoped to any one conversation)."""
        await self.broadcast_to_users(list(self._connections.keys()), event)


manager = ConnectionManager()
