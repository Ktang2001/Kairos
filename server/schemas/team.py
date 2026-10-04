"""Request and response shapes for the /teams routes."""

from datetime import datetime
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field

from server.schemas.auth import MAX_EMAIL_LENGTH, UserOut, to_user_out
from shared.text_rules import clean_display_text

if TYPE_CHECKING:
    from server.models.team import Team

MAX_TEAM_NAME_LENGTH = 100


class TeamNameIn(BaseModel):
    """Body of POST /teams and PATCH /teams/{id}.

    Whitespace is stripped before the length check, so "   " is rejected as
    empty rather than becoming a team with an invisible name.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    # Invisible/control characters stripped first, so two teams can't have
    # names that look identical (see shared.text_rules).
    name: Annotated[str, BeforeValidator(clean_display_text)] = Field(
        min_length=1, max_length=MAX_TEAM_NAME_LENGTH
    )


class AddMemberIn(BaseModel):
    """Body of POST /teams/{id}/members. Members are added by email, which is
    what a lead actually knows about a teammate; user ids are an internal detail.
    """

    email: str = Field(min_length=1, max_length=MAX_EMAIL_LENGTH)


class ChangeLeadIn(BaseModel):
    """Body of PUT /teams/{id}/lead. The new lead must already be a member."""

    user_id: int


class TeamSummary(BaseModel):
    """One row of GET /teams: enough to show a list without every member."""

    id: int
    name: str
    lead: UserOut
    member_count: int
    created_at: datetime


class TeamOut(BaseModel):
    """A team with its full member list."""

    id: int
    name: str
    lead: UserOut
    members: list[UserOut]
    created_at: datetime


def to_team_summary(team: "Team") -> TeamSummary:
    """Flatten an ORM ``Team`` into a list row: its lead and how many members."""
    return TeamSummary(
        id=team.id,
        name=team.name,
        lead=to_user_out(team.lead),
        member_count=len(team.members),
        created_at=team.created_at,
    )


def to_team_out(team: "Team") -> TeamOut:
    """Flatten an ORM ``Team`` with its full member list for the client."""
    return TeamOut(
        id=team.id,
        name=team.name,
        lead=to_user_out(team.lead),
        members=[to_user_out(member) for member in team.members],
        created_at=team.created_at,
    )
