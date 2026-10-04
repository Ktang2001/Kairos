"""Shapes for users as the teams and admin routes see them.

``UserOut`` is how a user is shown to clients (never the password hash);
``SetRoleIn`` is the body of PUT /users/{id}/role.
"""

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel

from shared.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_PROJECT_LEAD

if TYPE_CHECKING:
    from server.models.user import User


class UserOut(BaseModel):
    """A user as clients see them: id, name, email and app-wide role."""

    id: int
    name: str
    email: str
    role: str


def to_user_out(user: "User") -> UserOut:
    """Flatten an ORM ``User`` (and its role) for the client."""
    return UserOut(id=user.id, name=user.name, email=user.email, role=user.role.name)


class SetRoleIn(BaseModel):
    """Body of PUT /users/{id}/role. Only the three known roles are accepted."""

    role: Literal[ROLE_ADMIN, ROLE_PROJECT_LEAD, ROLE_MEMBER]  # type: ignore[valid-type]
