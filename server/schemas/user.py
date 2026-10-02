"""Request shapes for the admin /users routes (responses reuse ``UserOut``)."""

from typing import Literal

from pydantic import BaseModel

from shared.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_PROJECT_LEAD


class SetRoleIn(BaseModel):
    """Body of PUT /users/{id}/role. Only the three known roles are accepted."""

    role: Literal[ROLE_ADMIN, ROLE_PROJECT_LEAD, ROLE_MEMBER]  # type: ignore[valid-type]
