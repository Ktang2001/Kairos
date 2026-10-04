"""Shared FastAPI dependencies for authentication and authorisation.

``get_current_session`` turns a bearer token into the ``Session`` behind it, and
``get_current_user`` builds on that to produce the ``User``. Splitting the two
matters because logging out has to revoke the session itself.

The ``HTTPBearer`` security scheme is used instead of parsing the
``Authorization`` header by hand, so malformed headers are rejected consistently
and the generated OpenAPI docs grow a working "Authorize" button.

How a route uses this::

    def my_route(current_user: User = Depends(get_current_user)): ...

FastAPI then refuses the request with 401 unless it carries a live token.

MERGE-CRITICAL (whole file): every protected route identifies the caller
through ``get_current_user`` here. New routes from another branch (chat,
conversations, people, attachments...) must use it too, instead of trusting a
user id sent by the client (e.g. an ``X-Kairos-User-Id`` header), which
anyone can forge. Guarded by: tests/server/test_authorization.py.
"""

from collections.abc import Callable

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session as OrmSession

from server.db.session import get_db
from server.models.session import Session
from server.models.user import User
from server.services import session_service

#: ``auto_error=False`` so a missing or malformed header produces our own 401
#: with a WWW-Authenticate challenge. At the default, FastAPI answers a missing
#: header with 403, which means "you are known but not allowed" -- the wrong
#: signal for "you have not signed in".
bearer_scheme = HTTPBearer(auto_error=False, description="Token from POST /auth/login")


def _unauthorized(detail: str) -> HTTPException:
    """A 401 carrying the header that tells clients to sign in and send a bearer token."""
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),  # noqa: B008
    db: OrmSession = Depends(get_db),  # noqa: B008
) -> Session:
    """Resolve the caller's live session from their bearer token.

    Raises 401 for a missing header, an unknown token, a revoked session and an
    expired session alike. The four are deliberately indistinguishable in the
    response, so it cannot be used to probe which tokens exist.
    """
    if credentials is None or not credentials.credentials:
        raise _unauthorized("Not authenticated")

    session = session_service.resolve_session(db, credentials.credentials)
    if session is None:
        raise _unauthorized("Invalid or expired session")

    return session


def get_current_user(current_session: Session = Depends(get_current_session)) -> User:  # noqa: B008
    """Resolve the user behind the caller's session."""
    return current_session.user


def require_role(*allowed_roles: str) -> Callable[[User], User]:
    """Build a dependency that permits only the listed roles.

    This is the hook for context.md goal #2 (role-based access). Use it as a
    route dependency:

        @router.delete("/teams/{team_id}", dependencies=[Depends(require_role(ROLE_ADMIN))])
        def delete_team(team_id: int) -> None:
            ...

    A 403 (not 401) is correct here: the caller *is* authenticated, they simply
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
