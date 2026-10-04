"""Admin management of user accounts: listing them and changing roles.

Roles are app-wide (context.md): admin, project lead, member. Only admins may
change them (enforced by the route). One rule lives here: nobody may change
their *own* role. That stops an admin demoting themselves by accident and,
because only admins can change roles, it also guarantees the last admin can
never be removed -- it always takes a second admin to demote one.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.user import User
from server.services import auth_service


class UserNotFound(Exception):
    """No user has that id."""


class CannotChangeOwnRole(Exception):
    """Admins may not change their own role."""


def list_users(db: OrmSession) -> list[User]:
    """Every account, sorted by name (then id, for identical names)."""
    return list(
        db.scalars(
            select(User).options(selectinload(User.role)).order_by(func.lower(User.name), User.id)
        )
    )


def set_role(db: OrmSession, actor: User, *, user_id: int, role_name: str) -> User:
    """Change another user's role and return them. Raises CannotChangeOwnRole for your own account
    and UserNotFound for an unknown id.
    """
    if user_id == actor.id:
        raise CannotChangeOwnRole(user_id)

    user = db.scalar(select(User).options(selectinload(User.role)).where(User.id == user_id))
    if user is None:
        raise UserNotFound(user_id)

    role = auth_service.get_role_by_name(db, role_name)
    if role is None:  # pragma: no cover - the schema only admits known roles
        raise ValueError(f"unknown role: {role_name}")

    # The change takes effect on the user's very next request: permissions are
    # read from the database each time, not stored in their session token.
    user.role_id = role.id
    db.commit()
    return db.scalar(
        select(User)
        .options(selectinload(User.role))
        .where(User.id == user_id)
        .execution_options(populate_existing=True)
    )
