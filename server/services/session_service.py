"""Lifecycle of login sessions: create, resolve, revoke, purge.

Kept separate from ``auth_service`` because it answers a different question.
``auth_service`` decides *who* a caller is at the moment they log in; this
module decides whether the token they present afterwards is still good.

MERGE-CRITICAL: only a SHA-256 hash of each token is stored
(``hash_token``), never the token itself, so a copied database file cannot
be used to sign in as anyone. Keep it that way in any merged code that
creates or looks up sessions. Guarded by: tests/server/test_sessions.py.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession

from server.models.session import Session
from server.models.user import User
from server.services.auth_service import utcnow

#: How long a session stays usable without signing in again. Long enough not
#: to interrupt a work session, short enough that a token left behind on a
#: shared machine stops working on its own.
SESSION_LIFETIME = timedelta(days=14)

#: Live sessions one user may hold at once. Logging in beyond this ends the
#: oldest, so a stolen password cannot mint unlimited tokens and the table
#: cannot grow without bound. Ten covers several devices with room to spare.
MAX_SESSIONS_PER_USER = 10

#: Entropy of a bearer token, in bytes. 256 bits is far beyond guessing range,
#: which is also why the stored hash needs no salt: salting defends against
#: precomputation, and there is nothing to precompute for a random value.
TOKEN_BYTES = 32


def hash_token(token: str) -> str:
    """Return the SHA-256 hex digest stored in place of the raw token."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: OrmSession, user: User) -> tuple[Session, str]:
    """Open a session for ``user``; return it alongside the plaintext token.

    The plaintext token is handed back exactly once, to the caller who just
    logged in, and is never written to the database -- only its hash is.
    """
    token = secrets.token_urlsafe(TOKEN_BYTES)
    session = Session(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=utcnow() + SESSION_LIFETIME,
    )
    db.add(session)
    db.flush()
    _retire_excess_sessions(db, user.id, keep=MAX_SESSIONS_PER_USER)
    db.commit()
    db.refresh(session)
    return session, token


def _live_sessions(db: OrmSession, user_id: int):
    """A query for this user's sessions that are neither revoked nor expired."""
    return select(Session).where(
        Session.user_id == user_id,
        Session.revoked_at.is_(None),
        Session.expires_at > utcnow(),
    )


def _retire_excess_sessions(db: OrmSession, user_id: int, *, keep: int) -> None:
    """Revoke all but the ``keep`` newest live sessions of ``user_id``."""
    live = list(db.scalars(_live_sessions(db, user_id).order_by(Session.id.desc())))
    now = utcnow()
    for old in live[keep:]:
        old.revoked_at = now


def revoke_all_sessions(db: OrmSession, user: User) -> int:
    """Revoke every live session of ``user`` ("sign out everywhere")."""
    live = list(db.scalars(_live_sessions(db, user.id)))
    now = utcnow()
    for session in live:
        session.revoked_at = now
    db.commit()
    return len(live)


def resolve_session(db: OrmSession, token: str) -> Session | None:
    """Return the live session for ``token``, or None if it is unusable.

    Unusable means unknown, revoked, or expired. Callers must treat all three
    identically, or the response can be used to tell a guessable token from an
    expired one.
    """
    if not token:
        return None

    session = db.scalar(select(Session).where(Session.token_hash == hash_token(token)))

    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at <= utcnow():
        return None

    return session


def revoke_session(db: OrmSession, session: Session) -> None:
    """Retire a session so its token stops working immediately."""
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        db.commit()


def purge_expired_sessions(db: OrmSession) -> int:
    """Delete sessions that can no longer authenticate anything.

    Nothing depends on this for correctness -- ``resolve_session`` already
    rejects expired rows -- it just stops the table growing without bound.
    Revoked-but-unexpired rows are kept, because they still have to reject
    their token until it would have expired anyway.
    """
    result = db.execute(delete(Session).where(Session.expires_at <= utcnow()))
    db.commit()
    return result.rowcount or 0
