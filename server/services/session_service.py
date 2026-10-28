import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session as DbSession

from server.models.session import Session
from server.models.user import User

SESSION_IDLE_LIFETIME = timedelta(days=30)


def hash_token(token: str) -> str:
    """What the database stores for a login token: its SHA-256, in hex.

    Found by a security review: the raw tokens were stored, and database backups
    committed to the (public) repository on 2026-10-04 held six of them, still
    unexpired -- anyone reading the repo could sign in as those users. With only
    the hash stored, a leaked database holds nothing that signs anyone in. A
    plain fast hash is enough here (unlike passwords): the token is 256 random
    bits, so there is nothing to guess.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(frozen=True)
class IssuedSession:
    """A new login: the raw token (given to the client once, never stored) and its expiry."""

    token: str
    user_id: int
    expires_at: datetime


def create_session(db: DbSession, user_id: int) -> IssuedSession:
    """Issue a new opaque login token for `user_id` (called from signup/login).

    Replaces the old placeholder where the client just sent its own X-Kairos-User-Id
    header with nothing to prove it - this token is unguessable and only the server
    ever generates one. Only its hash is saved (see `hash_token`).
    """
    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    session = Session(
        token=hash_token(token),
        user_id=user_id,
        created_at=now,
        last_used_at=now,
        expires_at=now + SESSION_IDLE_LIFETIME,
    )
    db.add(session)
    db.commit()
    return IssuedSession(token=token, user_id=user_id, expires_at=session.expires_at)


def resolve_session(db: DbSession, token: str) -> User | None:
    """Look up the user behind `token`, or None if it's missing/expired.

    A valid lookup slides `expires_at` forward another SESSION_IDLE_LIFETIME - this
    is an idle timeout (inactivity), not a hard expiry from creation.
    """
    session = db.get(Session, hash_token(token))
    if session is None:
        return None

    now = datetime.now(UTC)
    expires_at = session.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at < now:
        return None

    user_id = session.user_id
    session.last_used_at = now
    session.expires_at = now + SESSION_IDLE_LIFETIME
    try:
        db.commit()
    except OperationalError:
        # Best effort: a read-only request whose snapshot went stale because
        # another request wrote at the same moment can't write this bump
        # (SQLite refuses at once in WAL mode). The session is still valid;
        # the next request slides the expiry instead of this one failing.
        db.rollback()

    return db.get(User, user_id)


def delete_session(db: DbSession, token: str) -> None:
    """Sign out: forget the session behind `token` (no-op if it's already gone)."""
    session = db.get(Session, hash_token(token))
    if session is not None:
        db.delete(session)
        db.commit()
