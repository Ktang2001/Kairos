"""Authentication routes.

Register, log in, log out, ask who you are, and one admin-only maintenance
route. Everything the routes do beyond translating input and output lives in
``server.services``.

How signing in works: ``/auth/login`` (or ``/auth/register``) checks the
password and hands back a random **token**. The client sends it with every
later request as ``Authorization: Bearer <token>``; ``server/api/deps.py``
turns it back into the signed-in user. Only a hash of the token is stored.

MERGE-CRITICAL (whole file): this is the token-based sign-in every other
route relies on (via ``get_current_user``). Another branch's simpler
``/auth/signup`` + ``/auth/login`` that return a user without a token, and
identify callers by an ``X-Kairos-User-Id`` header, must not replace it:
anyone could then act as anyone by changing one number. Merge new account
features *into* this file instead. If a route is renamed, also update
``NO_LOCK_PATHS`` in server/db/session.py and the client's
client/api_client/client.py. Guarded by: tests/server/test_auth.py,
test_sessions.py, test_security.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import get_current_session, get_current_user, require_role
from server.db.session import begin_write, get_db
from server.models.session import Session
from server.models.user import User
from server.schemas.auth import (
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    UserOut,
    to_user_out,
)
from server.services import auth_service, session_service
from shared.roles import ROLE_ADMIN

router = APIRouter(prefix="/auth", tags=["auth"])


def _build_login_response(session: Session, token: str, user: User) -> LoginResponse:
    """What register and login both answer: the token, when it expires, and
    who signed in. The token appears here once and is never stored as-is.
    """
    return LoginResponse(
        token=token,
        expires_at=session.expires_at,
        user=to_user_out(user),
    )


@router.post(
    "/register",
    response_model=LoginResponse,
    status_code=status.HTTP_201_CREATED,
)
def register(
    payload: RegisterRequest,
    db: OrmSession = Depends(get_db),  # noqa: B008
) -> LoginResponse:
    """Create an account and sign it in immediately.

    There is no ``role`` field in the request body on purpose: the role is
    assigned server-side (``member``), so a caller cannot register themselves
    as an administrator.
    """
    try:
        user = auth_service.register_user(
            db,
            name=payload.name,
            email=payload.email,
            password=payload.password,
        )
    except auth_service.EmailAlreadyRegistered:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered",
        ) from None
    except auth_service.UnknownRole as exc:
        # Only reachable if the roles table is empty, which start-up
        # (server.main.lifespan) prevents -- so seeing this means the rows were
        # deleted while the server was running. That is the server's fault,
        # not the caller's, so report it as a 500 rather than a 4xx.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server has no roles configured; restart the server",
        ) from exc

    # register_user committed and then re-read the new account; writing the
    # session in that same read transaction fails in WAL mode if anyone else
    # wrote meanwhile. Start a fresh write transaction (see begin_write).
    user_id = user.id
    begin_write(db)
    user = db.get(User, user_id)
    session, token = session_service.create_session(db, user)
    return _build_login_response(session, token, user)


def _wait_in_words(seconds: int) -> str:
    """Turn a lockout length into words for the error message ("2 minutes")."""
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = -(-seconds // 60)  # round up: "1 minute" for 61s would undersell it
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    request: Request,
    db: OrmSession = Depends(get_db),  # noqa: B008
) -> LoginResponse:
    """Exchange an email and password for a session token.

    Repeated failures lock that email from that computer for a while (see
    ``server.services.login_throttle``). A locked attempt is answered with
    429 before the password is checked at all.
    """
    # MERGE-CRITICAL: keep the lockout check before the password check. If
    # lost: unlimited password guessing. Guarded by: tests/server/test_security.py.
    throttle = request.app.state.login_throttle
    address = request.client.host if request.client else "unknown"

    wait = throttle.retry_after(payload.email, address)
    if wait:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed sign-in attempts. Try again in {_wait_in_words(wait)}.",
            headers={"Retry-After": str(wait)},
        )

    try:
        user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    except auth_service.InvalidCredentials:
        throttle.record_failure(payload.email, address)
        # One message for both "no such email" and "wrong password", so the
        # response cannot be used to discover which addresses have accounts.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None

    throttle.record_success(payload.email, address)
    # MERGE-CRITICAL: keep begin_write before create_session (also in
    # register above). The password check (slow) ran without the write lock;
    # take it now for the quick session write. If lost: simultaneous sign-ins
    # fail with 500 "database is locked". See server.db.session.begin_write.
    # Guarded by: tests/server/test_concurrency.py.
    user_id = user.id
    begin_write(db)
    user = db.get(User, user_id)
    session, token = session_service.create_session(db, user)
    return _build_login_response(session, token, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    current_session: Session = Depends(get_current_session),  # noqa: B008
    db: OrmSession = Depends(get_db),  # noqa: B008
) -> None:
    """Revoke the token used for this request.

    ``db`` is the same request-scoped session that ``get_current_session``
    used, because FastAPI caches dependency results within a request, so
    ``current_session`` is already attached to it.
    """
    session_service.revoke_session(db, current_session)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
def logout_all(
    current_user: User = Depends(get_current_user),  # noqa: B008
    db: OrmSession = Depends(get_db),  # noqa: B008
) -> None:
    """Sign out everywhere: revoke every live session of the caller, including
    this one. For "I think someone has my password" or a lost laptop.
    """
    session_service.revoke_all_sessions(db, current_user)


@router.get("/me", response_model=UserOut)
def read_current_user(current_user: User = Depends(get_current_user)) -> UserOut:  # noqa: B008
    """Return the account behind the presented token."""
    return to_user_out(current_user)


@router.post("/purge-expired-sessions")
def purge_expired_sessions(
    db: OrmSession = Depends(get_db),  # noqa: B008
    _admin: User = Depends(require_role(ROLE_ADMIN)),  # noqa: B008
) -> dict[str, int]:
    """Delete sessions that have already expired. Administrators only."""
    return {"purged": session_service.purge_expired_sessions(db)}
