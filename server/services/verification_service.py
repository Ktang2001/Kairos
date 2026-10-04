import hashlib
import hmac
import secrets
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session as DbSession

from server.models.pending_verification import PendingVerification
from server.models.user import User

CODE_LENGTH = 6
CODE_LIFETIME = timedelta(minutes=10)
MAX_ATTEMPTS = 5

_RESEND_COOLDOWN_SECONDS = 30.0
# In-memory only (per-process), same tradeoff as auth_service's login cooldown -
# keyed by lowercased email.
_last_sent_at: dict[str, float] = {}


def _hash_code(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _generate_code() -> str:
    """A 6-digit numeric code - `secrets`, not `random`, since this gates a real
    login/signup even though it's short-lived and attempt-limited."""
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


class ResendCooldownError(Exception):
    """Raised when a new code is requested for the same email too soon."""


def _check_resend_cooldown(email: str) -> None:
    last = _last_sent_at.get(email)
    if last is not None and time.monotonic() - last < _RESEND_COOLDOWN_SECONDS:
        raise ResendCooldownError(
            f"please wait {int(_RESEND_COOLDOWN_SECONDS)} seconds before requesting another code"
        )
    _last_sent_at[email] = time.monotonic()


def create_pending_verification(
    db: DbSession, user_id: int, email: str
) -> tuple[PendingVerification, str]:
    """Generates a fresh code, stores only its hash, and returns `(record, raw_code)`
    so the caller can email `raw_code` - it is never persisted in plaintext."""
    _check_resend_cooldown(email.strip().lower())

    code = _generate_code()
    now = datetime.now(UTC)
    record = PendingVerification(
        token=secrets.token_urlsafe(32),
        user_id=user_id,
        code_hash=_hash_code(code),
        created_at=now,
        expires_at=now + CODE_LIFETIME,
        attempt_count=0,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record, code


def resend_verification(db: DbSession, token: str) -> tuple[str, str]:
    """Issues a fresh code for an existing pending attempt (the user asked for a
    new one, e.g. the first email never arrived), replacing the old code.
    Returns `(email, code)` so the caller can send it."""
    record = db.get(PendingVerification, token)
    if record is None:
        raise ValueError("unknown or expired verification attempt")

    user = db.get(User, record.user_id)
    if user is None:
        raise ValueError("unknown or expired verification attempt")

    _check_resend_cooldown(user.email)

    code = _generate_code()
    record.code_hash = _hash_code(code)
    record.expires_at = datetime.now(UTC) + CODE_LIFETIME
    record.attempt_count = 0
    db.commit()
    return user.email, code


def verify_code(db: DbSession, token: str, submitted_code: str) -> int | None:
    """Returns the verified `user_id` on success, or None if the token is
    missing/expired/locked-out or the code is wrong. A correct code is one-time
    use (the record is deleted); a wrong one counts against MAX_ATTEMPTS, after
    which the whole pending attempt is invalidated and must be restarted."""
    record = db.get(PendingVerification, token)
    if record is None:
        return None

    expires_at = record.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < datetime.now(UTC):
        db.delete(record)
        db.commit()
        return None

    if hmac.compare_digest(_hash_code(submitted_code), record.code_hash):
        user_id = record.user_id
        db.delete(record)
        db.commit()
        return user_id

    record.attempt_count += 1
    if record.attempt_count >= MAX_ATTEMPTS:
        db.delete(record)
    db.commit()
    return None
