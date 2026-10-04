"""Team management: create, rename, delete, and change membership (goal #1).

Who may do what:

* Admins and project leads may create a team. The creator becomes its lead
  and first member. (Enforced by the route, with ``require_role``.)
* A team is *managed* by its lead and by any admin. Managing means renaming,
  deleting, adding/removing members and handing over the lead.
* Any member may remove themselves (leave), except the lead, who has to hand
  the lead to someone else first so the team is never left without one.
* A team is visible only to its members and to admins. To everyone else it
  does not exist: they get ``TeamNotFound`` (404), not a 403, so team ids
  cannot be probed to learn which teams exist.

Routes translate the exceptions below into HTTP status codes.
"""

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.project import Project
from server.models.team import Team
from server.models.user import User
from server.services import auth_service
from shared.roles import ROLE_ADMIN


class TeamError(Exception):
    """Base class for team operations the API can refuse."""


class TeamNotFound(TeamError):
    """No such team, or the caller is not allowed to know it exists."""


class NotTeamManager(TeamError):
    """The caller can see the team but is neither its lead nor an admin."""


class TeamNameTaken(TeamError):
    """Another team already has this name (compared case-insensitively)."""


class TeamHasProjects(TeamError):
    """Deleting the team would orphan its projects."""


class UserNotFound(TeamError):
    """No account has the given email."""


class AlreadyMember(TeamError):
    """The user is already on the team."""


class NotAMember(TeamError):
    """The user is not on the team."""


class LeadCannotBeRemoved(TeamError):
    """The lead must hand the lead to someone else before leaving."""


class NewLeadNotAMember(TeamError):
    """Only an existing member can become the lead."""


def is_admin(user: User) -> bool:
    """True if the user has the app-wide admin role."""
    return user.role.name == ROLE_ADMIN


def can_manage(team: Team, user: User) -> bool:
    """True if ``user`` may rename, delete or change the membership of ``team``."""
    return is_admin(user) or team.lead_id == user.id


def _is_member(team: Team, user_id: int) -> bool:
    """True if the user with this id is on the team."""
    return any(member.id == user_id for member in team.members)


def _team_query() -> Select[tuple[Team]]:
    """Select teams with the lead, the members and their roles eagerly loaded.

    Eager rather than lazy because the response builders read ``lead.role`` and
    every ``member.role``; ``populate_existing`` so a team re-read straight
    after a commit reflects the committed rows, not a stale identity-map copy.
    """
    return (
        select(Team)
        .options(
            selectinload(Team.lead).selectinload(User.role),
            selectinload(Team.members).selectinload(User.role),
        )
        .execution_options(populate_existing=True)
    )


def _load(db: OrmSession, team_id: int) -> Team | None:
    """The team with its lead and members loaded, or None if there is no such team."""
    return db.scalar(_team_query().where(Team.id == team_id))


def _reload(db: OrmSession, team_id: int) -> Team:
    """Like ``_load``, for a team the caller has just written (so it must exist)."""
    team = _load(db, team_id)
    if team is None:  # pragma: no cover - the caller just committed this row
        raise TeamError(f"team {team_id} disappeared immediately after a write")
    return team


def _name_taken(db: OrmSession, name: str, *, exclude_team_id: int | None = None) -> bool:
    """Is ``name`` already used by another team, ignoring case?

    Both sides go through SQL ``lower()`` so this check agrees exactly with the
    ``uq_teams_name_lower`` index. (SQLite's ``lower()`` folds ASCII letters
    only, so "Équipe" and "équipe" count as different names; that matches the
    index, which is what matters.)
    """
    stmt = select(Team.id).where(func.lower(Team.name) == func.lower(name))
    if exclude_team_id is not None:
        stmt = stmt.where(Team.id != exclude_team_id)
    return db.scalar(stmt) is not None


def _commit_or_name_taken(db: OrmSession) -> None:
    """Commit, reporting a lost race on the unique name index as TeamNameTaken."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise TeamNameTaken() from exc


def create_team(db: OrmSession, *, name: str, creator: User) -> Team:
    """Create a team led by ``creator``, who also becomes its first member."""
    if _name_taken(db, name):
        raise TeamNameTaken(name)

    team = Team(name=name, lead_id=creator.id, members=[creator])
    db.add(team)
    _commit_or_name_taken(db)
    return _reload(db, team.id)


def list_teams_for(db: OrmSession, user: User) -> list[Team]:
    """Teams ``user`` belongs to, or every team for an admin, sorted by name."""
    stmt = _team_query().order_by(func.lower(Team.name), Team.id)
    if not is_admin(user):
        stmt = stmt.where(Team.members.any(User.id == user.id))
    return list(db.scalars(stmt))


def get_visible_team(db: OrmSession, team_id: int, user: User) -> Team:
    """Return the team if ``user`` may see it, else raise TeamNotFound."""
    team = _load(db, team_id)
    if team is None or not (is_admin(user) or _is_member(team, user.id)):
        raise TeamNotFound(team_id)
    return team


def get_managed_team(db: OrmSession, team_id: int, user: User) -> Team:
    """Return the team if ``user`` may manage it.

    Visibility is checked first, so a non-member gets TeamNotFound rather than
    NotTeamManager and learns nothing about the team.
    """
    team = get_visible_team(db, team_id, user)
    if not can_manage(team, user):
        raise NotTeamManager(team_id)
    return team


def rename_team(db: OrmSession, team_id: int, actor: User, *, name: str) -> Team:
    """Rename a team (its lead or an admin only). Raises TeamNameTaken if another team already uses
    the name, ignoring case.
    """
    team = get_managed_team(db, team_id, actor)
    if _name_taken(db, name, exclude_team_id=team.id):
        raise TeamNameTaken(name)

    team.name = name
    _commit_or_name_taken(db)
    return _reload(db, team.id)


def delete_team(db: OrmSession, team_id: int, actor: User) -> None:
    """Delete a team and its memberships.

    Refused while the team still owns projects: deleting it would leave those
    projects (and their tasks) pointing at a team that no longer exists.
    """
    team = get_managed_team(db, team_id, actor)

    project_count = db.scalar(
        select(func.count()).select_from(Project).where(Project.team_id == team.id)
    )
    if project_count:
        raise TeamHasProjects(team_id)

    # Deleting through the ORM also deletes this team's team_members rows,
    # because ``members`` is a many-to-many relationship. SQLite would not do
    # it on its own: foreign keys are not enforced (see context.md).
    db.delete(team)
    db.commit()


def add_member(db: OrmSession, team_id: int, actor: User, *, email: str) -> Team:
    """Add the account with ``email`` to the team."""
    team = get_managed_team(db, team_id, actor)

    user = auth_service.get_user_by_email(db, email)
    if user is None:
        raise UserNotFound(email)
    if _is_member(team, user.id):
        raise AlreadyMember(user.id)

    team.members.append(user)
    try:
        db.commit()
    except IntegrityError as exc:
        # Two simultaneous adds of the same person: the composite primary key
        # on team_members lets only one through.
        db.rollback()
        raise AlreadyMember(user.id) from exc
    return _reload(db, team.id)


def remove_member(db: OrmSession, team_id: int, actor: User, *, user_id: int) -> None:
    """Remove ``user_id`` from the team. Managers may remove anyone but the
    lead; any member may remove themselves (leave) unless they are the lead.
    """
    team = get_visible_team(db, team_id, actor)

    if actor.id != user_id and not can_manage(team, actor):
        raise NotTeamManager(team_id)

    member = next((m for m in team.members if m.id == user_id), None)
    if member is None:
        raise NotAMember(user_id)
    if member.id == team.lead_id:
        raise LeadCannotBeRemoved(user_id)

    team.members.remove(member)
    db.commit()


def change_lead(db: OrmSession, team_id: int, actor: User, *, new_lead_id: int) -> Team:
    """Hand the lead to another member. The old lead stays on as a member."""
    team = get_managed_team(db, team_id, actor)

    if not _is_member(team, new_lead_id):
        raise NewLeadNotAMember(new_lead_id)

    if team.lead_id != new_lead_id:
        team.lead_id = new_lead_id
        db.commit()
    return _reload(db, team.id)
