"""Builds the Gantt chart for a project (GET /projects/{id}/gantt).

Read-only: it turns a project's tasks, subtasks and dependencies into rows a
client can draw. Who may see it is the project's rule: the team's members and
admins (``project_service.get_visible_project``).
"""

from datetime import date, datetime

from sqlalchemy.orm import Session as OrmSession

from server.models.subtask import Subtask
from server.models.task import Task
from server.models.user import User
from server.schemas.gantt import GanttOut, GanttRow, ScheduleConflict
from server.schemas.meeting import as_utc
from server.schemas.user import to_user_out
from server.services import project_service, task_service
from server.services.dashboard_service import local_today
from server.services.task_service import utcnow
from shared.statuses import TaskStatus

#: Progress shown for an in-progress task with no subtasks to count.
IN_PROGRESS_WITHOUT_SUBTASKS = 50


def bar_dates(start: date | None, due: date | None) -> tuple[date | None, date | None, bool]:
    """The bar's ``(start, end, estimated)``.

    Both dates: drawn as given. One date: a one-day bar on it, ``estimated``.
    Neither: ``(None, None, False)``, i.e. unscheduled.
    """
    if start is not None and due is not None:
        return start, due, False
    only = start or due
    if only is None:
        return None, None, False
    return only, only, True


def task_progress(task: Task) -> int:
    """How far along a task is, 0-100.

    Done is 100. Otherwise, with subtasks, the share of them that are done
    (rounded down, so an unfinished task never shows 100). Without subtasks:
    0 for to-do, ``IN_PROGRESS_WITHOUT_SUBTASKS`` for in progress.
    """
    if task.status == TaskStatus.DONE:
        return 100
    if task.subtasks:
        done = sum(1 for s in task.subtasks if s.status == TaskStatus.DONE)
        return min(99, done * 100 // len(task.subtasks))
    if task.status == TaskStatus.IN_PROGRESS:
        return IN_PROGRESS_WITHOUT_SUBTASKS
    return 0


def _subtask_progress(status: str) -> int:
    """A subtask's bar: empty to do, half in progress (like a task with no
    subtasks), full done."""
    if status == TaskStatus.DONE:
        return 100
    if status == TaskStatus.IN_PROGRESS:
        return IN_PROGRESS_WITHOUT_SUBTASKS
    return 0


def _is_overdue(item: Task | Subtask, end: date | None, today: date, now: datetime) -> bool:
    """Not done, and past its exact deadline (``due_at``, naive UTC) -- the same
    moment for everyone, whatever their time zone. A bar with no deadline
    (only a start date, so an estimated end) is late once that end day has
    passed."""
    if item.status == TaskStatus.DONE:
        return False
    if item.due_at is not None:
        return item.due_at < now
    return end is not None and end < today


def _task_row(task: Task, today: date, now: datetime) -> GanttRow:
    """A task's bar."""
    start, end, estimated = bar_dates(task.start_date, task.due_date)
    return GanttRow(
        kind="task",
        id=task.id,
        parent_task_id=None,
        title=task.title,
        status=TaskStatus(task.status),
        assignee=to_user_out(task.assignee) if task.assignee else None,
        start=start,
        end=end,
        estimated=estimated,
        progress=task_progress(task),
        due_at=as_utc(task.due_at),
        overdue=_is_overdue(task, end, today, now),
        depends_on=[other.id for other in task.depends_on],
    )


def _subtask_row(subtask: Subtask, today: date, now: datetime) -> GanttRow:
    """A subtask's bar."""
    start, end, estimated = bar_dates(subtask.start_date, subtask.due_date)
    return GanttRow(
        kind="subtask",
        id=subtask.id,
        parent_task_id=subtask.task_id,
        title=subtask.title,
        status=TaskStatus(subtask.status),
        assignee=to_user_out(subtask.assignee) if subtask.assignee else None,
        start=start,
        end=end,
        estimated=estimated,
        progress=_subtask_progress(subtask.status),
        due_at=as_utc(subtask.due_at),
        overdue=_is_overdue(subtask, end, today, now),
        depends_on=[],
    )


def _conflicts(tasks: list[Task]) -> list[ScheduleConflict]:
    """Dependencies whose dates are in the wrong order.

    A task should start after the task it waits on ends. Only checked when both
    bars have dates; finished prerequisites are not flagged.
    """
    found = []
    for task in tasks:
        start, _, _ = bar_dates(task.start_date, task.due_date)
        for other in task.depends_on:
            if other.status == TaskStatus.DONE:
                continue
            _, other_end, _ = bar_dates(other.start_date, other.due_date)
            if start is not None and other_end is not None and start <= other_end:
                found.append(ScheduleConflict(task_id=task.id, depends_on_id=other.id))
    return found


def get_project_gantt(
    db: OrmSession, project_id: int, actor: User, *, today: date | None = None
) -> GanttOut:
    """The Gantt chart for one project. Raises ProjectNotFound if the actor may not see it.

    ``today`` is the viewer's own date (``dashboard_service.viewer_today``);
    without it, the hosting computer's.
    """
    project, _ = project_service.get_visible_project(db, project_id, actor)
    tasks = task_service.load_project_tasks(db, project.id)
    today = today or local_today()
    now = utcnow()

    rows: list[GanttRow] = []
    unscheduled: list[GanttRow] = []

    def start_order(task: Task) -> tuple[bool, date, int]:
        start, _, _ = bar_dates(task.start_date, task.due_date)
        return (start is None, start or date.min, task.id)

    for task in sorted(tasks, key=start_order):
        row = _task_row(task, today, now)
        (rows if row.start is not None else unscheduled).append(row)
        for subtask in task.subtasks:
            sub_row = _subtask_row(subtask, today, now)
            (rows if sub_row.start is not None else unscheduled).append(sub_row)

    return GanttOut(
        project_id=project.id,
        project_name=project.name,
        today=today,
        range_start=min((r.start for r in rows if r.start), default=None),
        range_end=max((r.end for r in rows if r.end), default=None),
        rows=rows,
        unscheduled=unscheduled,
        conflicts=_conflicts(tasks),
    )
