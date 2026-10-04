"""Placeholder current-user resolution.

No real authentication exists yet - accounts/login are being built separately. This
module is the ONE place that resolves "who is making this request": callers just
trust a client-supplied id, with no password or session check. This is a known,
temporary gap (anyone on the network can currently claim to be any user id,
including an admin) that must be closed once real auth lands. Every protected route
depends only on `get_current_user_id`/`require_global_admin`, so swapping in real
auth later means changing only the bodies of these two functions - no call sites.
"""

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.models.user import User

PLACEHOLDER_USER_HEADER = "X-Kairos-User-Id"


def get_current_user_id(
    x_kairos_user_id: int | None = Header(default=None, alias=PLACEHOLDER_USER_HEADER),
    db: Session = Depends(get_db),  # noqa: B008
) -> int:
    """Resolve the calling user from a client-supplied header. PLACEHOLDER - no credential check."""
    if x_kairos_user_id is None or db.get(User, x_kairos_user_id) is None:
        raise HTTPException(status_code=401, detail="Missing or unknown placeholder user id")
    return x_kairos_user_id


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


def resolve_ws_user_id(db: Session, user_id: int) -> int | None:
    """Same placeholder check as `get_current_user_id`, for the WebSocket handshake.

    The WS handshake takes `user_id` as a query param rather than a header, and uses
    a manually managed session rather than `Depends(get_db)` (see server/api/ws_chat.py).
    """
    user = db.get(User, user_id)
    return user.id if user is not None else None
