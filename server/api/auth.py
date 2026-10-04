import smtplib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server import email_sender
from server.api.dependencies import get_current_token
from server.db.session import get_db
from server.models.user import User
from server.schemas.auth import (
    AuthResult,
    LoginRequest,
    PendingVerificationResult,
    ResendCodeRequest,
    SignupRequest,
    VerifyCodeRequest,
)
from server.services import auth_service, session_service, verification_service
from server.services.auth_service import TooManyAttemptsError
from server.services.verification_service import ResendCooldownError

router = APIRouter(prefix="/auth", tags=["auth"])

# Anything send_verification_code can raise when the host hasn't configured SMTP
# correctly (missing env vars - RuntimeError) or the send itself fails (bad
# credentials, can't reach smtp.gmail.com, etc.) - all surfaced as a clean 503
# rather than an unhandled 500 (see server/email_sender.py).
_EMAIL_SEND_ERRORS = (RuntimeError, smtplib.SMTPException, OSError)


def _send_code_or_503(email: str, code: str) -> None:
    try:
        email_sender.send_verification_code(email, code)
    except _EMAIL_SEND_ERRORS as exc:
        raise HTTPException(
            status_code=503, detail=f"Could not send the verification email: {exc}"
        ) from exc


def _issue_auth_result(db: Session, user) -> AuthResult:
    session = session_service.create_session(db, user.id)
    return AuthResult(id=user.id, name=user.name, email=user.email, token=session.token)


def _start_verification(db: Session, user) -> PendingVerificationResult:
    """Common tail of signup/login: password check already passed, but a real
    session isn't issued until the emailed code is confirmed (see
    POST /auth/verify-code). The resend cooldown (server/services/verification_service.py)
    applies here too - a double-submitted signup/login within the cooldown
    window must 429, not crash."""
    try:
        record, code = verification_service.create_pending_verification(db, user.id, user.email)
    except ResendCooldownError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    _send_code_or_503(user.email, code)
    return PendingVerificationResult(pending_token=record.token, email=user.email)


@router.post("/signup", response_model=AuthResult)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> AuthResult:  # noqa: B008
    """Creates a real account (hashed password) and issues a session immediately -
    no email step. 2FA is login-only (see POST /auth/login) - gating signup too
    was judged more friction than it was worth for this app's two-person scale.
    """
    try:
        user = auth_service.create_user(
            db,
            name=payload.name,
            email=payload.email,
            password=payload.password,
            two_factor_enabled=payload.two_factor_enabled,
        )
    except ValueError as exc:
        status_code = 409 if "already registered" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return _issue_auth_result(db, user)


@router.post("/login", response_model=AuthResult | PendingVerificationResult)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db),  # noqa: B008
) -> AuthResult | PendingVerificationResult:
    """Password check, then - only for accounts that opted in at signup
    (User.two_factor_enabled) - 2FA: a real session isn't issued until the
    emailed code is confirmed via POST /auth/verify-code (see
    server/services/verification_service.py). Everyone else gets a session
    immediately, same as signup always does."""
    try:
        user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    except TooManyAttemptsError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    if not user.two_factor_enabled:
        return _issue_auth_result(db, user)
    return _start_verification(db, user)


@router.post("/verify-code", response_model=AuthResult)
def verify_code(
    payload: VerifyCodeRequest,
    db: Session = Depends(get_db),  # noqa: B008
) -> AuthResult:
    """The second step of signup/login - confirms the emailed code and, only
    then, issues the real session (see server/services/session_service.py)."""
    user_id = verification_service.verify_code(db, payload.pending_token, payload.code)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Incorrect or expired code")

    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect or expired code")
    return _issue_auth_result(db, user)


@router.post("/resend-code", response_model=PendingVerificationResult)
def resend_code(
    payload: ResendCodeRequest,
    db: Session = Depends(get_db),  # noqa: B008
) -> PendingVerificationResult:
    try:
        email, code = verification_service.resend_verification(db, payload.pending_token)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ResendCooldownError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc

    _send_code_or_503(email, code)
    return PendingVerificationResult(pending_token=payload.pending_token, email=email)


@router.post("/logout", status_code=204)
def logout(
    token: str = Depends(get_current_token),
    db: Session = Depends(get_db),  # noqa: B008
) -> None:
    session_service.delete_session(db, token)
