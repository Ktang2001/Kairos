"""Admin-only user management (context.md goal #2): list accounts and change
their app-wide role. Rules live in ``server.services.user_service``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import require_role
from server.api.errors import KNOWN_ERRORS, http_error
from server.db.session import get_db
from server.models.user import User
from server.schemas.user import SetRoleIn, UserOut, to_user_out
from server.services import user_service
from shared.roles import ROLE_ADMIN

router = APIRouter(prefix="/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(
    db: OrmSession = Depends(get_db),  # noqa: B008
    _admin: User = Depends(require_role(ROLE_ADMIN)),  # noqa: B008
) -> list[UserOut]:
    """Every account, sorted by name. Admins only."""
    return [to_user_out(user) for user in user_service.list_users(db)]


@router.put("/{user_id}/role", response_model=UserOut)
def set_role(
    user_id: int,
    payload: SetRoleIn,
    db: OrmSession = Depends(get_db),  # noqa: B008
    admin: User = Depends(require_role(ROLE_ADMIN)),  # noqa: B008
) -> UserOut:
    """Change someone's role. Admins only, and never your own."""
    try:
        user = user_service.set_role(db, admin, user_id=user_id, role_name=payload.role)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_user_out(user)
