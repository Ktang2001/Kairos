"""Tasks and subtasks (goals #4-6).

Permissions come from the team that owns the task's project:

* Any member of that team (or an admin) may create, view and edit tasks and
  subtasks: title, description, assignee, due date, status.
* Only the team's lead or an admin may delete them.
* Anyone else gets ``TaskNotFound``/``SubtaskNotFound``, never a 403, so ids
  cannot be probed -- the same rule as teams and projects.

An assignee must be a member of the owning team. When someone leaves a team
their tasks there are unassigned (``team_service.remove_member``).
"""

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.subtask import Subtask
from server.models.task import Task
from server.models.team import Team
from server.models.user import User
from server.services import project_service, team_service
from server.services.auth_service import utcnow
from shared.statuses import TaskStatus


class TaskNotFound(Exception):
    """No such task, or the caller may not see the team that owns it."""


class SubtaskNotFound(Exception):
    """No such subtask, or the caller may not see the team that owns it."""


class AssigneeNotOnTeam(Exception):
    """The proposed assignee is not a member of the owning team (or does not exist)."""


def _task_query():
    """Tasks with everything the response builders read, loaded up front."""
    return (
        select(Task)
        .options(
            selectinload(Task.assignee).selectinload(User.role),
            selectinload(Task.subtasks).selectinload(Subtask.assignee).selectinload(User.role),
            selectinload(Task.project),
        )
        .execution_options(populate_existing=True)
    )


def _check_assignee(team: Team, assignee_id: int | None) -> None:
    """Allow ``None`` (unassigned) or a member of ``team``.

    An id that matches no user at all gets the same error as a non-member, so
    the response cannot be used to discover which user ids exist.
    """
    if assignee_id is not None and not any(m.id == assignee_id for m in team.members):
        raise AssigneeNotOnTeam(assignee_id)


def _apply_status(task: Task, status: TaskStatus) -> None:
    """Set the status, keeping ``completed_at`` in step with it.

    Re-saving "done" on a task that is already done keeps the original time:
    otherwise an unrelated edit would make old work look freshly finished.
    """
    if status == TaskStatus.DONE and task.status != TaskStatus.DONE:
        task.completed_at = utcnow()
    elif status != TaskStatus.DONE:
        task.completed_at = None
    task.status = status


def _reload_task(db: OrmSession, task_id: int) -> Task:
    task = db.scalar(_task_query().where(Task.id == task_id))
    if task is None:  # pragma: no cover - the caller just committed this row
        raise TaskNotFound(task_id)
    return task


def get_visible_task(db: OrmSession, task_id: int, user: User) -> tuple[Task, Team]:
    task = db.scalar(_task_query().where(Task.id == task_id))
    if task is None:
        raise TaskNotFound(task_id)
    try:
        _, team = project_service.get_visible_project(db, task.project_id, user)
    except project_service.ProjectNotFound:
        raise TaskNotFound(task_id) from None
    return task, team


# ---------------------------------------------------------------------- tasks


def create_task(
    db: OrmSession,
    project_id: int,
    actor: User,
    *,
    title: str,
    description: str | None,
    assignee_id: int | None,
    due_date: date | None,
    status: TaskStatus,
) -> Task:
    project, team = project_service.get_visible_project(db, project_id, actor)
    _check_assignee(team, assignee_id)

    task = Task(
        project_id=project.id,
        title=title,
        description=description,
        assignee_id=assignee_id,
        due_date=due_date,
        status=TaskStatus.TODO,
    )
    _apply_status(task, status)
    db.add(task)
    db.commit()
    return _reload_task(db, task.id)


def list_tasks(
    db: OrmSession,
    project_id: int,
    actor: User,
    *,
    status: TaskStatus | None = None,
    assignee_id: int | None = None,
) -> list[Task]:
    """The project's tasks, soonest due first; tasks with no due date last."""
    project, _ = project_service.get_visible_project(db, project_id, actor)
    stmt = (
        _task_query()
        .where(Task.project_id == project.id)
        .order_by(Task.due_date.is_(None), Task.due_date, Task.id)
    )
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    return list(db.scalars(stmt))


def update_task(db: OrmSession, task_id: int, actor: User, changes: dict[str, Any]) -> Task:
    """Apply ``changes`` (only the fields the client sent) to the task."""
    task, team = get_visible_task(db, task_id, actor)

    if "assignee_id" in changes:
        _check_assignee(team, changes["assignee_id"])

    for field, value in changes.items():
        if field == "status":
            _apply_status(task, value)
        else:
            setattr(task, field, value)
    db.commit()
    return _reload_task(db, task.id)


def delete_task(db: OrmSession, task_id: int, actor: User) -> None:
    """Delete a task and its subtasks. Lead or admin only."""
    task, team = get_visible_task(db, task_id, actor)
    if not team_service.can_manage(team, actor):
        raise team_service.NotTeamManager(team.id)
    db.delete(task)
    db.commit()


# ------------------------------------------------------------------- subtasks


def _get_visible_subtask(db: OrmSession, subtask_id: int, user: User) -> tuple[Subtask, Team]:
    subtask = db.get(Subtask, subtask_id)
    if subtask is None:
        raise SubtaskNotFound(subtask_id)
    try:
        _, team = get_visible_task(db, subtask.task_id, user)
    except TaskNotFound:
        raise SubtaskNotFound(subtask_id) from None
    return subtask, team


def create_subtask(
    db: OrmSession,
    task_id: int,
    actor: User,
    *,
    title: str,
    assignee_id: int | None,
    due_date: date | None,
    status: TaskStatus,
) -> Task:
    """Add a subtask. Returns the parent task, so the client sees the new progress."""
    task, team = get_visible_task(db, task_id, actor)
    _check_assignee(team, assignee_id)

    db.add(
        Subtask(
            task_id=task.id,
            title=title,
            assignee_id=assignee_id,
            due_date=due_date,
            status=status,
        )
    )
    db.commit()
    return _reload_task(db, task.id)


def update_subtask(db: OrmSession, subtask_id: int, actor: User, changes: dict[str, Any]) -> Task:
    """Apply ``changes`` to the subtask. Returns the parent task."""
    subtask, team = _get_visible_subtask(db, subtask_id, actor)

    if "assignee_id" in changes:
        _check_assignee(team, changes["assignee_id"])

    for field, value in changes.items():
        setattr(subtask, field, value)
    db.commit()
    return _reload_task(db, subtask.task_id)


def delete_subtask(db: OrmSession, subtask_id: int, actor: User) -> None:
    """Delete a subtask. Lead or admin only."""
    subtask, team = _get_visible_subtask(db, subtask_id, actor)
    if not team_service.can_manage(team, actor):
        raise team_service.NotTeamManager(team.id)
    db.delete(subtask)
    db.commit()
