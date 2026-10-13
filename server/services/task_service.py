"""Tasks, subtasks and task dependencies (goals #4-6, and the Gantt chart).

Permissions come from the team that owns the task's project:

* Any member of that team (or an admin) may create, view and edit tasks and
  subtasks: title, description, assignee, start and due dates, status. They may
  also add and remove dependencies between tasks.
* Only the team's lead or an admin may delete tasks and subtasks.
* Anyone else gets ``TaskNotFound``/``SubtaskNotFound``, never a 403, so ids
  cannot be probed -- the same rule as teams and projects.

An assignee must be a member of the owning team. When someone leaves a team
their tasks there are unassigned (``team_service.remove_member``).

Dependencies ("B cannot start until A is done") link two tasks in the same
project and may never form a loop: a loop has no valid order, so a Gantt
chart could not draw it.
"""

from collections import deque
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.subtask import Subtask
from server.models.task import Task
from server.models.team import Team
from server.models.user import User
from server.services import project_service, team_service
from shared.statuses import TaskStatus


def utcnow() -> datetime:
    """The current time as naive UTC, the form ``Task.completed_at`` stores."""
    return datetime.now(UTC).replace(tzinfo=None)


class TaskNotFound(Exception):
    """No such task, or the caller may not see the team that owns it."""


class SubtaskNotFound(Exception):
    """No such subtask, or the caller may not see the team that owns it."""


class AssigneeNotOnTeam(Exception):
    """The proposed assignee is not a member of the owning team (or does not exist)."""


class StartAfterDue(Exception):
    """The change would leave the start date after the due date."""


class DependencyNotInProject(Exception):
    """The other task does not exist, or is in a different project."""


class DependencyCycle(Exception):
    """The link would make a task (directly or indirectly) wait on itself."""


class DependencyNotFound(Exception):
    """The task does not depend on that other task."""


def _task_query():
    """Tasks with everything the response builders read, loaded up front."""
    return (
        select(Task)
        .options(
            selectinload(Task.assignee).selectinload(User.role),
            selectinload(Task.subtasks).selectinload(Subtask.assignee).selectinload(User.role),
            selectinload(Task.project),
            selectinload(Task.depends_on),
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


def _check_dates(item: Task | Subtask, changes: dict[str, Any]) -> None:
    """Refuse a PATCH that would put the start after the due date.

    Only one end may be sent, so compare with the stored value of the other.
    """
    start: date | None = changes.get("start_date", item.start_date)
    due: date | None = changes.get("due_date", item.due_date)
    if start is not None and due is not None and start > due:
        raise StartAfterDue(item.id)


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
    """The task as just committed, with everything the response needs loaded."""
    task = db.scalar(_task_query().where(Task.id == task_id))
    if task is None:  # pragma: no cover - the caller just committed this row
        raise TaskNotFound(task_id)
    return task


def get_visible_task(db: OrmSession, task_id: int, user: User) -> tuple[Task, Team]:
    """Return the task and its team if ``user`` may see them, else TaskNotFound."""
    task = db.scalar(_task_query().where(Task.id == task_id))
    if task is None:
        raise TaskNotFound(task_id)
    try:
        _, team = project_service.get_visible_project(db, task.project_id, user)
    except project_service.ProjectNotFound:
        raise TaskNotFound(task_id) from None
    return task, team


def load_project_tasks(db: OrmSession, project_id: int) -> list[Task]:
    """Every task in the project, with subtasks, assignees and dependencies loaded.

    No permission check: callers check the project first (``gantt_service``).
    """
    return list(db.scalars(_task_query().where(Task.project_id == project_id).order_by(Task.id)))


# ---------------------------------------------------------------------- tasks


def create_task(
    db: OrmSession,
    project_id: int,
    actor: User,
    *,
    title: str,
    description: str | None,
    assignee_id: int | None,
    start_date: date | None,
    due_date: date | None,
    status: TaskStatus,
) -> Task:
    """Create a task in a project the actor can see. The assignee must be on the team."""
    project, team = project_service.get_visible_project(db, project_id, actor)
    _check_assignee(team, assignee_id)

    task = Task(
        project_id=project.id,
        title=title,
        description=description,
        assignee_id=assignee_id,
        start_date=start_date,
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
    _check_dates(task, changes)

    for field, value in changes.items():
        if field == "status":
            _apply_status(task, value)
        else:
            setattr(task, field, value)
    db.commit()
    return _reload_task(db, task.id)


def delete_task(db: OrmSession, task_id: int, actor: User) -> None:
    """Delete a task, its subtasks and its dependency links. Lead or admin only."""
    task, team = get_visible_task(db, task_id, actor)
    if not team_service.can_manage(team, actor):
        raise team_service.NotTeamManager(team.id)
    db.delete(task)
    db.commit()


# --------------------------------------------------------------- dependencies


def _reaches(start: Task, target_id: int) -> bool:
    """True if ``start`` already waits on ``target_id``, directly or through other tasks."""
    seen: set[int] = set()
    queue = deque([start])
    while queue:
        current = queue.popleft()
        if current.id == target_id:
            return True
        if current.id in seen:
            continue
        seen.add(current.id)
        queue.extend(current.depends_on)
    return False


def add_dependency(db: OrmSession, task_id: int, actor: User, *, depends_on_id: int) -> Task:
    """Make ``task_id`` wait on ``depends_on_id``. Adding a link that exists is a no-op.

    Refused if the other task is not in the same project, or if the link would
    close a loop (including a task waiting on itself).
    """
    task, _ = get_visible_task(db, task_id, actor)

    other = db.get(Task, depends_on_id)
    if other is None or other.project_id != task.project_id:
        raise DependencyNotInProject(depends_on_id)
    if any(existing.id == other.id for existing in task.depends_on):
        return task
    # Adding task -> other closes a loop exactly when other already reaches task.
    if _reaches(other, task.id):
        raise DependencyCycle(task.id)

    task.depends_on.append(other)
    try:
        db.commit()
    except IntegrityError:
        # Two simultaneous adds of the same link: the primary key lets one through.
        db.rollback()
    return _reload_task(db, task_id)


def remove_dependency(db: OrmSession, task_id: int, actor: User, *, depends_on_id: int) -> Task:
    """Remove the link "``task_id`` waits on ``depends_on_id``"."""
    task, _ = get_visible_task(db, task_id, actor)
    link = next((other for other in task.depends_on if other.id == depends_on_id), None)
    if link is None:
        raise DependencyNotFound(depends_on_id)
    task.depends_on.remove(link)
    db.commit()
    return _reload_task(db, task_id)


# ------------------------------------------------------------------- subtasks


def _get_visible_subtask(db: OrmSession, subtask_id: int, user: User) -> tuple[Subtask, Team]:
    """Return the subtask and its team if ``user`` may see them, else SubtaskNotFound."""
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
    start_date: date | None,
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
            start_date=start_date,
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
    _check_dates(subtask, changes)

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
