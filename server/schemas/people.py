from pydantic import BaseModel


class UserSummary(BaseModel):
    """A minimal, public-safe view of a user for search/picker UI - no password_hash, no role."""

    id: int
    name: str
    email: str

    model_config = {"from_attributes": True}


class UserProfile(UserSummary):
    """The caller's own profile, including their global role - only ever returned
    for the authenticated caller themselves (see GET /people/me), never for anyone
    else, since role isn't public information.
    """

    role: str
