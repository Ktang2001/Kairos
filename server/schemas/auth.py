"""Request and response shapes for the /auth routes.

A "schema" is the exact shape a request body must have; FastAPI rejects
anything else with 422 before the route runs, so routes never see bad input.

Pydantic's ``EmailStr`` would need the ``email-validator`` package, which this
project does not depend on, so the address check is a small regex from
``shared.account_rules`` (see there for why it is deliberately permissive).

MERGE-CRITICAL: keep the limits and validators below (lengths, the email
check, ``password_problem``, ``clean_display_text``, and *no* ``role`` field
on RegisterRequest). A bare ``name: str; email: str; password: str`` version
accepts megabyte-long names, "password123", invisible characters that let
one name impersonate another, and lets the client choose its own role.
Guarded by: tests/server/test_auth.py and test_security.py.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, BeforeValidator, Field, ValidationInfo, field_validator

# Defined in shared/ so the Qt client can check forms against the same rules;
# re-exported here because server code imports them from this module.
from shared.account_rules import (
    EMAIL_PATTERN,
    MAX_EMAIL_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    password_problem,
)
from shared.text_rules import clean_display_text

if TYPE_CHECKING:
    # Imported only for type checkers: a schema should not pull ORM models into
    # the runtime import graph when an annotation is all it needs.
    from server.models.user import User

__all__ = [
    "EMAIL_PATTERN",
    "MAX_EMAIL_LENGTH",
    "MAX_NAME_LENGTH",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "LoginRequest",
    "LoginResponse",
    "RegisterRequest",
    "UserOut",
    "to_user_out",
]


class RegisterRequest(BaseModel):
    """Body of POST /auth/register. Note: there is no role field.

    Fields are declared name, email, password in that order on purpose: the
    password check reads the already-validated name and email.
    """

    #: Invisible/control characters are stripped first (see shared.text_rules),
    #: so a name cannot be made to look like someone else's.
    name: Annotated[str, BeforeValidator(clean_display_text)] = Field(
        min_length=1, max_length=MAX_NAME_LENGTH
    )
    email: str = Field(max_length=MAX_EMAIL_LENGTH)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)

    @field_validator("email")
    @classmethod
    def email_must_look_like_an_address(cls, value: str) -> str:
        """Reject anything that doesn't look like name@domain (the same rule the client checks)."""
        candidate = value.strip()
        if not EMAIL_PATTERN.match(candidate):
            raise ValueError("must be an email address")
        return candidate

    @field_validator("password")
    @classmethod
    def password_must_not_be_guessable(cls, value: str, info: ValidationInfo) -> str:
        """Reject common passwords and ones containing the user's name or email (see
        shared.account_rules).
        """
        problem = password_problem(
            value, email=info.data.get("email", ""), name=info.data.get("name", "")
        )
        if problem:
            raise ValueError(problem)
        return value


class LoginRequest(BaseModel):
    """Body of POST /auth/login."""

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class UserOut(BaseModel):
    """A user as clients see them. Never includes ``password_hash``."""

    id: int
    name: str
    email: str
    role: str


class LoginResponse(BaseModel):
    """Returned by both login and registration on success.

    Registration signs the new user in straight away, so the client does not
    have to make a second round trip with credentials it already has.
    """

    token: str
    token_type: str = "bearer"
    expires_at: datetime
    user: UserOut


def to_user_out(user: "User") -> UserOut:
    """Flatten an ORM ``User`` (and its ``role`` relationship) for the client.

    Explicit rather than ``model_validate(user)`` so that ``role`` is reduced
    to its name here, where it is visible, instead of relying on a validator
    to unwrap a ``Role`` object.
    """
    return UserOut(id=user.id, name=user.name, email=user.email, role=user.role.name)
