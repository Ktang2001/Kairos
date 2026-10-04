"""Current-user resolution from a real login session token.

Replaces the old placeholder (a trusted-with-no-proof X-Kairos-User-Id header,
still visible in git history) now that signup/login issue real session tokens -
see server/services/session_service.py. Every protected route still depends only
on `get_current_user_id`/`require_global_admin`, so this remains the one place
that resolves "who is making this request".
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.models.user import User
from server.services import session_service

AUTH_HEADER = "Authorization"
AUTH_SCHEME_PREFIX = "Bearer "


def _extract_bearer_token(authorization: str | None) -> str | None:
    if authorization is None or not authorization.startswith(AUTH_SCHEME_PREFIX):
        return None
    token = authorization[len(AUTH_SCHEME_PREFIX) :].strip()
    return token or None


def get_current_token(
    authorization: str | None = Header(default=None, alias=AUTH_HEADER),
) -> str:
    """The raw bearer token, for routes (like logout) that need to delete it rather
    than just resolve the user behind it."""
    token = _extract_bearer_token(authorization)
    if token is None:
        raise HTTPException(status_code=401, detail="Missing or malformed Authorization header")
    return token


def get_current_user_id(
    token: str = Depends(get_current_token),
    db: Session = Depends(get_db),  # noqa: B008
) -> int:
    """Resolve the calling user from their session token. 401 if missing/unknown/expired."""
    user = session_service.resolve_session(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return user.id


def require_global_admin(
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> int:
    """Like `get_current_user_id`, but also requires the site-wide admin Role.

    This is the global Role from server/models/role.py (users.role_id), not the
    per-conversation ParticipantRole used for group-chat membership.
    """
    user = db.get(User, current_user_id)
    if user is None or user.role is None or user.role.name != "admin":
        raise HTTPException(status_code=403, detail="Requires global admin role")
    return current_user_id


def resolve_ws_user_id(db: Session, token: str) -> int | None:
    """Same session lookup as `get_current_user_id`, for the WebSocket handshake.

    The WS handshake takes `token` as a query param rather than a header (browsers/Qt
    WebSocket clients can't always set custom headers on the handshake), and uses a
    manually managed session rather than `Depends(get_db)` (see server/api/ws_chat.py).
    """
    user = session_service.resolve_session(db, token)
    return user.id if user is not None else None
