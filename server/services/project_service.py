"""Projects belong to a team and borrow its permissions (goals #5-6).

* Visible to the team's members and to admins; to everyone else a project
  does not exist (``ProjectNotFound``), exactly like its team.
* Created, renamed, re-statused and deleted by the team's lead or an admin.
* Deleting a project deletes its tasks and their subtasks (ORM cascade on
  ``Project.tasks`` and ``Task.subtasks``).
"""

from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.project import Project
from server.models.team import Team
from server.models.user import User
from server.services import team_service
from shared.statuses import ProjectStatus


class ProjectNotFound(Exception):
    """No such project, or the caller may not see the team that owns it."""


def _project_query() -> Select[tuple[Project]]:
    """Projects with their tasks loaded, for the per-status counts in responses."""
    return (
        select(Project)
        .options(selectinload(Project.tasks))
        .execution_options(populate_existing=True)
    )


def get_visible_project(db: OrmSession, project_id: int, user: User) -> tuple[Project, Team]:
    """Return the project and its team if ``user`` may see them.

    A hidden team's project raises ``ProjectNotFound``, not ``TeamNotFound``,
    so the response does not even confirm the project id exists.
    """
    project = db.scalar(_project_query().where(Project.id == project_id))
    if project is None:
        raise ProjectNotFound(project_id)
    try:
        team = team_service.get_visible_team(db, project.team_id, user)
    except team_service.TeamNotFound:
        raise ProjectNotFound(project_id) from None
    return project, team


def get_managed_project(db: OrmSession, project_id: int, user: User) -> Project:
    project, team = get_visible_project(db, project_id, user)
    if not team_service.can_manage(team, user):
        raise team_service.NotTeamManager(team.id)
    return project


def _reload(db: OrmSession, project_id: int) -> Project:
    project = db.scalar(_project_query().where(Project.id == project_id))
    if project is None:  # pragma: no cover - the caller just committed this row
        raise ProjectNotFound(project_id)
    return project


def create_project(
    db: OrmSession, team_id: int, actor: User, *, name: str, description: str | None
) -> Project:
    team = team_service.get_managed_team(db, team_id, actor)
    project = Project(
        team_id=team.id,
        name=name,
        description=description,
        status=ProjectStatus.ACTIVE,
    )
    db.add(project)
    db.commit()
    return _reload(db, project.id)


def list_projects(db: OrmSession, team_id: int, actor: User) -> list[Project]:
    """The team's projects, active ones first, then by name."""
    team = team_service.get_visible_team(db, team_id, actor)
    stmt = (
        _project_query()
        .where(Project.team_id == team.id)
        .order_by(Project.status != ProjectStatus.ACTIVE, func.lower(Project.name), Project.id)
    )
    return list(db.scalars(stmt))


def update_project(
    db: OrmSession, project_id: int, actor: User, changes: dict[str, Any]
) -> Project:
    """Apply ``changes`` (only the fields the client sent) to the project."""
    project = get_managed_project(db, project_id, actor)
    for field, value in changes.items():
        setattr(project, field, value)
    db.commit()
    return _reload(db, project.id)


def delete_project(db: OrmSession, project_id: int, actor: User) -> None:
    """Delete the project with all of its tasks and subtasks."""
    project = get_managed_project(db, project_id, actor)
    db.delete(project)
    db.commit()
