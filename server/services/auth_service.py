import hashlib
import hmac
import os
import time

from sqlalchemy.orm import Session

from server.models.role import Role
from server.models.user import User

_PBKDF2_ITERATIONS = 200_000
_MIN_PASSWORD_LENGTH = 8
DEFAULT_SIGNUP_ROLE = "member"

_MAX_FAILED_ATTEMPTS = 5
_COOLDOWN_SECONDS = 30.0
# In-memory only (per-process) - resets on server restart, which is an acceptable
# tradeoff at this app's two-person LAN scale. Keyed by lowercased email.
_failed_login_attempts: dict[str, list[float]] = {}


def _is_cooling_down(email: str) -> bool:
    """True if `email` has hit _MAX_FAILED_ATTEMPTS within the last _COOLDOWN_SECONDS."""
    now = time.monotonic()
    attempts = [t for t in _failed_login_attempts.get(email, []) if now - t < _COOLDOWN_SECONDS]
    _failed_login_attempts[email] = attempts
    return len(attempts) >= _MAX_FAILED_ATTEMPTS


def _record_failed_attempt(email: str) -> None:
    _failed_login_attempts.setdefault(email, []).append(time.monotonic())


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


def _get_or_create_role(db: Session, name: str) -> Role:
    role = db.query(Role).filter_by(name=name).first()
    if role is None:
        role = Role(name=name)
        db.add(role)
        db.flush()
    return role


def create_user(db: Session, name: str, email: str, password: str) -> User:
    """Sign up a new account. Always created with the default member role - role
    promotion is a separate, out-of-scope governance action.
    """
    name = name.strip()
    email = email.strip().lower()
    if not name:
        raise ValueError("name is required")
    if "@" not in email:
        raise ValueError("a valid email is required")
    if len(password) < _MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
    if db.query(User).filter_by(email=email).first() is not None:
        raise ValueError("that email is already registered")

    role = _get_or_create_role(db, DEFAULT_SIGNUP_ROLE)
    user = User(name=name, email=email, password_hash=hash_password(password), role_id=role.id)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


class TooManyAttemptsError(Exception):
    """Raised when an email has failed login too many times recently."""


def authenticate(db: Session, email: str, password: str) -> User | None:
    email = email.strip().lower()
    if _is_cooling_down(email):
        raise TooManyAttemptsError(
            f"too many failed attempts - try again in {int(_COOLDOWN_SECONDS)} seconds"
        )

    user = db.query(User).filter_by(email=email).first()
    if user is None or not verify_password(password, user.password_hash):
        _record_failed_attempt(email)
        return None

    _clear_failed_attempts(email)
    return user
