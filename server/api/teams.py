"""Team routes (context.md goal #1).

The rules about who may do what live in ``server.services.team_service``; this
module only checks the app-wide role needed to create a team, calls the
service, and maps its exceptions to HTTP status codes via ``server.api.errors``.
"""

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import get_current_user, require_role
from server.api.errors import KNOWN_ERRORS, http_error
from server.db.session import get_db
from server.models.user import User
from server.schemas.team import (
    AddMemberIn,
    ChangeLeadIn,
    TeamNameIn,
    TeamOut,
    TeamSummary,
    to_team_out,
    to_team_summary,
)
from server.services import team_service
from shared.roles import ROLE_ADMIN, ROLE_PROJECT_LEAD

router = APIRouter(prefix="/teams", tags=["teams"])


@router.post("", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def create_team(
    payload: TeamNameIn,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(require_role(ROLE_ADMIN, ROLE_PROJECT_LEAD)),  # noqa: B008
) -> TeamOut:
    """Create a team. The caller becomes its lead and first member."""
    try:
        team = team_service.create_team(db, name=payload.name, creator=current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_team_out(team)


@router.get("", response_model=list[TeamSummary])
def list_teams(
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> list[TeamSummary]:
    """Teams the caller belongs to (admins: every team), sorted by name."""
    return [to_team_summary(team) for team in team_service.list_teams_for(db, current_user)]


@router.get("/{team_id}", response_model=TeamOut)
def get_team(
    team_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TeamOut:
    """One team with its members. 404 unless the caller is on it or an admin."""
    try:
        team = team_service.get_visible_team(db, team_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_team_out(team)


@router.patch("/{team_id}", response_model=TeamOut)
def rename_team(
    team_id: int,
    payload: TeamNameIn,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TeamOut:
    """Rename a team. Its lead or an admin only; names are unique ignoring case."""
    try:
        team = team_service.rename_team(db, team_id, current_user, name=payload.name)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_team_out(team)


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> Response:
    """Delete a team. Its lead or an admin only; refused while it still has projects."""
    try:
        team_service.delete_team(db, team_id, current_user)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{team_id}/members", response_model=TeamOut, status_code=status.HTTP_201_CREATED)
def add_member(
    team_id: int,
    payload: AddMemberIn,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TeamOut:
    """Add a user by email. Returns the team with its updated member list."""
    try:
        team = team_service.add_member(db, team_id, current_user, email=payload.email)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_team_out(team)


@router.delete("/{team_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    team_id: int,
    user_id: int,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> Response:
    """Remove a member, or leave the team when ``user_id`` is your own id."""
    try:
        team_service.remove_member(db, team_id, current_user, user_id=user_id)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{team_id}/lead", response_model=TeamOut)
def change_lead(
    team_id: int,
    payload: ChangeLeadIn,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> TeamOut:
    """Hand the lead to another member. The old lead stays on the team."""
    try:
        team = team_service.change_lead(db, team_id, current_user, new_lead_id=payload.user_id)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return to_team_out(team)
