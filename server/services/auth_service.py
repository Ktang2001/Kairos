"""Accounts: sign-up, password checks, and the role lookups the rest of the
server uses.

Sign-in (PBKDF2 passwords, the per-email cooldown, ``create_user`` and
``authenticate``) is the Kaleb branch's design, kept as is. The role helpers at
the bottom (``ensure_roles``, ``get_role_by_name``, ``get_user_by_email``) came
from the Nick2 branch with its team and admin features; they never touch
passwords.
"""

import functools
import hashlib
import hmac
import os
import time

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from server.models.role import Role
from server.models.user import User
from shared.account_rules import (
    EMAIL_PATTERN,
    MAX_EMAIL_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PASSWORD_LENGTH,
)
from shared.roles import ALL_ROLES
from shared.text_rules import clean_display_text

_PBKDF2_ITERATIONS = 200_000
_MIN_PASSWORD_LENGTH = 8
DEFAULT_SIGNUP_ROLE = "member"

_MAX_FAILED_ATTEMPTS = 5
#: After _MAX_FAILED_ATTEMPTS wrong passwords the email is locked this long;
#: each further failure doubles it, up to _MAX_LOCKOUT_SECONDS. Found by a
#: security review: a flat 30 s lock after every 5 failures still allowed
#: ~14,000 guesses a day per account; this allows about 240.
_COOLDOWN_SECONDS = 30.0
_MAX_LOCKOUT_SECONDS = 15 * 60.0
#: Failures older than this are forgotten.
_FAILURE_MEMORY_SECONDS = 60 * 60.0
#: When the table tracks more emails than this, entries with no recent failures
#: are dropped, so guessing at made-up emails can't grow it without limit.
_MAX_TRACKED_EMAILS = 10_000
# In-memory only (per-process) - resets on server restart, which is an acceptable
# tradeoff at this app's two-person LAN scale. Keyed by lowercased email.
_failed_login_attempts: dict[str, list[float]] = {}


def _recent_failures(email: str, now: float) -> list[float]:
    """The email's failure times within _FAILURE_MEMORY_SECONDS (older ones are dropped)."""
    attempts = [
        t for t in _failed_login_attempts.get(email, []) if now - t < _FAILURE_MEMORY_SECONDS
    ]
    if attempts:
        _failed_login_attempts[email] = attempts
    else:
        _failed_login_attempts.pop(email, None)
    return attempts


def _lockout_remaining(email: str) -> float:
    """Seconds until `email` may try again (0 when it isn't locked).

    The lock runs from the most recent failure: _COOLDOWN_SECONDS once there are
    _MAX_FAILED_ATTEMPTS failures, doubling with each failure after that.
    """
    now = time.monotonic()
    attempts = _recent_failures(email, now)
    if len(attempts) < _MAX_FAILED_ATTEMPTS:
        return 0.0
    extra = len(attempts) - _MAX_FAILED_ATTEMPTS
    lockout = min(_COOLDOWN_SECONDS * 2**extra, _MAX_LOCKOUT_SECONDS)
    return max(0.0, attempts[-1] + lockout - now)


def _is_cooling_down(email: str) -> bool:
    """True while `email` is locked out after too many wrong passwords."""
    return _lockout_remaining(email) > 0


def _record_failed_attempt(email: str) -> None:
    """Note one wrong password for `email`, pruning the table if it has grown large."""
    now = time.monotonic()
    if len(_failed_login_attempts) >= _MAX_TRACKED_EMAILS:
        for tracked in list(_failed_login_attempts):
            _recent_failures(tracked, now)
    _failed_login_attempts.setdefault(email, []).append(now)


def _clear_failed_attempts(email: str) -> None:
    _failed_login_attempts.pop(email, None)


def hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 with a random salt - stdlib only, no new dependency.

    Stored as "<salt-hex>$<digest-hex>" in User.password_hash.
    """
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    expected = bytes.fromhex(digest_hex)
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, _PBKDF2_ITERATIONS)
    return hmac.compare_digest(actual, expected)


@functools.cache
def _dummy_hash() -> str:
    """A real-looking stored hash to check passwords against for unknown emails."""
    return hash_password("no account has this password")


def _get_or_create_role(db: Session, name: str) -> Role:
    role = db.query(Role).filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        db.add(role)
        db.flush()
    return role


def create_user(
    db: Session, name: str, email: str, password: str, two_factor_enabled: bool = False
) -> User:
    """Sign up a new account. Always created with the default member role - role
    promotion is a separate, out-of-scope governance action. `two_factor_enabled`
    is the signer-upper's own choice (a checkbox on the signup form - see
    client/views/auth_dialog.py) of whether POST /auth/login will require an
    emailed code; it has no effect on signup itself, which never does 2FA.
    """
    # The shared limits are enforced here too, not only by the client: found by
    # a security review, the server took a 1 MB password, unlimited names and
    # emails, and names made of invisible characters.
    name = clean_display_text(name)
    email = email.strip().lower()
    if not name:
        raise ValueError("name is required")
    if len(name) > MAX_NAME_LENGTH:
        raise ValueError(f"name can be at most {MAX_NAME_LENGTH} characters")
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(email):
        raise ValueError("a valid email is required")
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"password can be at most {MAX_PASSWORD_LENGTH} characters")
    if db.query(User).filter_by(email=email).first() is not None:
        raise ValueError("that email is already registered")

    role = _get_or_create_role(db, DEFAULT_SIGNUP_ROLE)
    user = User(
        name=name,
        email=email,
        password_hash=hash_password(password),
        role_id=role.id,
        two_factor_enabled=two_factor_enabled,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TooManyAttemptsError(Exception):
    """Raised when an email has failed login too many times recently."""


def authenticate(db: Session, email: str, password: str) -> User | None:
    email = email.strip().lower()
    wait = _lockout_remaining(email)
    if wait > 0:
        raise TooManyAttemptsError(
            f"too many failed attempts - try again in {int(wait) + 1} seconds"
        )

    user = db.query(User).filter_by(email=email).first()
    # An unknown email still costs one full password check, so the reply takes
    # as long as for a real account: found by a security review, the time
    # difference (3 ms vs 40 ms) told an attacker which emails have accounts.
    stored = user.password_hash if user is not None else _dummy_hash()
    if not verify_password(password[: MAX_PASSWORD_LENGTH + 1], stored) or user is None:
        _record_failed_attempt(email)
        return None

    _clear_failed_attempts(email)
    return user


# ------------------------------------------------- roles and lookups (Nick2)


def normalise_email(email: str) -> str:
    """Fold an email to the form it is stored in (trimmed, lower case)."""
    return email.strip().lower()


def ensure_roles(db: Session) -> list[Role]:
    """Create any missing roles and return them all, most privileged first.

    Run at every server start (``server.main.lifespan``): the migrations create
    the ``roles`` table but no rows, and teams/admin features need all three.
    Safe to call repeatedly.
    """
    existing = {role.name: role for role in db.scalars(select(Role))}
    created = False
    for role_name in ALL_ROLES:
        if role_name not in existing:
            existing[role_name] = Role(name=role_name)
            db.add(existing[role_name])
            created = True
    if created:
        db.commit()
    return [existing[role_name] for role_name in ALL_ROLES]


def get_role_by_name(db: Session, role_name: str) -> Role | None:
    """The role row named "admin", "project_lead" or "member", or None."""
    return db.scalar(select(Role).where(Role.name == role_name))


def get_user_by_email(db: Session, email: str) -> User | None:
    """Look a user up by email, with their role loaded straight away (callers
    read ``user.role.name`` after the request's session may have closed).
    """
    return db.scalar(
        select(User).options(selectinload(User.role)).where(User.email == normalise_email(email))
    )
