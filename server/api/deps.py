"""Who is calling, as the teams, users and messages routes need it.

The token check itself is the Kaleb branch's (``server/api/dependencies.py``:
``get_current_user_id`` reads ``Authorization: Bearer <token>`` and looks the
session up). This module turns that id into the ``User`` row, with its role, and
adds ``require_role`` for the app-wide roles (admin / project_lead / member)
that came from the Nick2 branch.

How a route uses this::

    def my_route(current_user: User = Depends(get_current_user)): ...
    def admin_only(admin: User = Depends(require_role(ROLE_ADMIN))): ...

MERGE-CRITICAL (whole file): every protected route identifies the caller through
``get_current_user`` here or ``get_current_user_id`` in dependencies.py -- never
through a user id sent by the client, which anyone can forge.
Guarded by: tests/server/test_authorization.py.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.api.dependencies import get_current_user_id
from server.db.session import get_db
from server.models.user import User


def get_current_user(
    user_id: int = Depends(get_current_user_id),
    db: OrmSession = Depends(get_db),  # noqa: B008
) -> User:
    """The signed-in user, with their role loaded. 401 without a live token.

    Read from the database on every request, so a role change takes effect on
    the user's very next request.
    """
    user = db.scalar(select(User).options(selectinload(User.role)).where(User.id == user_id))
    if user is None:  # pragma: no cover - the session lookup just found this user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user


def require_role(*allowed_roles: str) -> Callable[[User], User]:
    """Build a dependency that permits only the listed app-wide roles.

    A 403 (not 401) is correct here: the caller *is* signed in, they simply
    are not allowed to do this.
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:  # noqa: B008
        """Let the request through only if the caller's role is one of ``allowed_roles``."""
        if current_user.role.name not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of: {', '.join(allowed_roles)}",
            )
        return current_user

    return dependency
