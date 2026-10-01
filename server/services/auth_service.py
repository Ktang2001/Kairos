"""Registration and authentication for Kairos users.

Business rules live here rather than in the routes (context.md: the Qt client
stays thin and all logic is server-side so both clients stay in sync). Routes
translate the exceptions defined below into HTTP status codes.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.role import Role
from server.models.user import User
from server.services import password_service
from shared.roles import ALL_ROLES, DEFAULT_SELF_REGISTRATION_ROLE


class AuthError(Exception):
    """Base class for registration/authentication failures the API can report."""


class EmailAlreadyRegistered(AuthError):
    """Registration refused: another account already uses that email."""


class InvalidCredentials(AuthError):
    """Login refused. Deliberately does not say whether the email exists."""


class UnknownRole(AuthError):
    """The requested role is not one this application knows about."""


def utcnow() -> datetime:
    """Current UTC time as a *naive* datetime.

    Naive on purpose: SQLite stores DATETIME without a timezone, and comparing
    an aware datetime against a naive one raises TypeError. Everything that
    touches created_at/expires_at goes through here so the two never mix.
    """
    return datetime.now(UTC).replace(tzinfo=None)


def normalise_email(email: str) -> str:
    """Fold an email to its canonical form.

    Without this, ``Alice@example.com`` and ``alice@example.com`` would be two
    separate accounts, and the unique constraint on the column would not catch
    the duplicate.
    """
    return email.strip().lower()


def ensure_roles(db: OrmSession) -> list[Role]:
    """Create any missing roles and return them all, in privilege order.

    Idempotent, so it is safe to call on every start-up, which is where the
    app calls it (``server.main.lifespan``). The migrations create the
    ``roles`` table but put no rows in it, so without this call a fresh
    database has no roles and every registration fails.
    """
    existing = {role.name: role for role in db.scalars(select(Role))}

    created = False
    for role_name in ALL_ROLES:
        if role_name not in existing:
            role = Role(name=role_name)
            db.add(role)
            existing[role_name] = role
            created = True

    if created:
        db.commit()

    return [existing[role_name] for role_name in ALL_ROLES]


def get_role_by_name(db: OrmSession, role_name: str) -> Role | None:
    return db.scalar(select(Role).where(Role.name == role_name))


def get_user_by_email(db: OrmSession, email: str) -> User | None:
    """Look a user up by email, with their role eagerly loaded.

    ``selectinload`` rather than a lazy load, because callers reach straight for
    ``user.role.name`` -- frequently after the request-scoped session has
    closed, where a lazy load raises DetachedInstanceError instead.
    """
    return db.scalar(
        select(User).options(selectinload(User.role)).where(User.email == normalise_email(email))
    )


def register_user(
    db: OrmSession,
    *,
    name: str,
    email: str,
    password: str,
    role_name: str = DEFAULT_SELF_REGISTRATION_ROLE,
) -> User:
    """Create a user, or raise ``AuthError`` if that is not possible.

    ``role_name`` defaults to the least-privileged role and is never taken
    from client input on the public route, so nobody can self-register as an
    administrator.
    """
    email = normalise_email(email)

    if get_user_by_email(db, email) is not None:
        raise EmailAlreadyRegistered(email)

    role = get_role_by_name(db, role_name)
    if role is None:
        raise UnknownRole(role_name)

    user = User(
        name=name.strip(),
        email=email,
        password_hash=password_service.hash_password(password),
        role_id=role.id,
    )
    db.add(user)

    try:
        db.commit()
    except IntegrityError as exc:
        # Two registrations for the same email can pass the check above at the
        # same time; the unique index is the real arbiter, so report the same
        # outcome rather than letting a 500 escape.
        db.rollback()
        raise EmailAlreadyRegistered(email) from exc

    # Re-read rather than ``db.refresh(user)``: committing expires every
    # attribute, and refresh would restore only the columns, leaving ``role``
    # to load lazily -- which fails as soon as the caller's session closes.
    created = get_user_by_email(db, email)
    if created is None:  # pragma: no cover - the row was committed a line ago
        raise AuthError("user disappeared immediately after being created")

    return created


def authenticate(db: OrmSession, *, email: str, password: str) -> User:
    """Return the user matching these credentials, or raise InvalidCredentials.

    A hash is computed even when the email is unknown, so the response time
    does not reveal which addresses are registered.
    """
    user = get_user_by_email(db, email)

    if user is None:
        password_service.verify_password(password, password_service.dummy_hash())
        raise InvalidCredentials(email)

    if not password_service.verify_password(password, user.password_hash):
        raise InvalidCredentials(email)

    return user
