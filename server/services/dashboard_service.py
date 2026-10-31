"""Project statistics for the dashboard (context.md goal #7).

Everything is computed from the teams the viewer can see -- their own teams,
or every team for an admin -- so the dashboard never reveals work in a team
the viewer is not on.

Figures are computed in Python over the loaded tasks rather than with SQL
aggregates. At class-project scale (hundreds to low thousands of tasks) that
is fast and far easier to read and test; if it ever becomes slow, this is the
one module to rewrite.
"""

from datetime import UTC, date, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.project import Project
from server.models.subtask import Subtask
from server.models.task import Task
from server.models.team import Team
from server.models.user import User
from server.schemas.dashboard import (
    DashboardOut,
    MyWork,
    Overview,
    ProjectStats,
    SubtaskBrief,
    TaskBrief,
    Workload,
)
from server.schemas.meeting import as_utc, to_meeting_out
from server.schemas.project import count_statuses
from server.schemas.user import to_user_out
from server.services import meeting_service, team_service
from shared.statuses import ProjectStatus, TaskStatus

#: "Due soon" means due between today and this many days from today, inclusive.
DUE_SOON_DAYS = 7
#: "Completed recently" means marked done within this many days.
RECENT_DAYS = 7
#: How many of the viewer's next deadlines ``my_work.upcoming`` lists.
UPCOMING_LIMIT = 5
#: How many upcoming meetings ``meetings`` lists.
MEETINGS_LIMIT = 10


def local_today() -> date:
    """Today's date on the hosting computer, in its own time zone.

    Due dates are calendar dates as people mean them ("due Friday"), so they
    are compared with the local date, not the UTC one -- in the evening in the
    Americas, UTC is already tomorrow.
    """
    return datetime.now(UTC).astimezone().date()


class TodayOutOfRange(Exception):
    """A client's "today" is more than a day from the server's UTC date: no
    time zone is that far off, so that computer's clock is wrong."""


def viewer_today(requested: date | None, now: datetime | None = None) -> date:
    """The day "due soon" and the Gantt chart's today line are measured from:
    the viewer's own date, when their client sends it.

    Teammates can be in different time zones, and near midnight their dates
    differ; each should see the days counted from their own calendar, not the
    host computer's. Time zones run from UTC-12 to UTC+14, so a real local
    date is the UTC date or the day either side of it; anything further means
    a wrong clock and is refused. A client that sends no date (older
    versions) gets the host computer's date. ``now`` is naive UTC.
    """
    if requested is None:
        return local_today()
    utc_date = (now or datetime.now(UTC).replace(tzinfo=None)).date()
    if abs((requested - utc_date).days) > 1:
        raise TodayOutOfRange(requested)
    return requested


class Clock(NamedTuple):
    """When the dashboard is measured: the host's local ``today`` (deadlines'
    calendar days) and ``now`` (naive UTC, deadlines' exact moments)."""

    today: date
    now: datetime


def _is_open(task: Task | Subtask) -> bool:
    return task.status != TaskStatus.DONE


def _is_overdue(task: Task | Subtask, clock: Clock) -> bool:
    """Open and past its exact deadline (``due_at``), whatever time zone anyone
    is in. A row from before deadlines had times falls back to its date: due
    *before* today. No deadline is never overdue.
    """
    if not _is_open(task):
        return False
    if task.due_at is not None:
        return task.due_at < clock.now
    return task.due_date is not None and task.due_date < clock.today


def _is_due_soon(task: Task | Subtask, clock: Clock) -> bool:
    """Open, not overdue yet, and due on one of the next ``DUE_SOON_DAYS`` days
    (today included). Counted in calendar days: "due soon" is a rough window,
    "overdue" is the exact moment."""
    return (
        _is_open(task)
        and not _is_overdue(task, clock)
        and task.due_date is not None
        and clock.today <= task.due_date <= clock.today + timedelta(days=DUE_SOON_DAYS)
    )


def _deadline_order(item: Task | Subtask) -> tuple:
    """Soonest deadline first: by day, then exact time, then id."""
    return (item.due_date, item.due_at or datetime.max, item.id)


def _percent(done: int, total: int) -> float:
    return round(done / total * 100, 1) if total else 0.0


def build_dashboard(db: OrmSession, viewer: User, *, today: date, now: datetime) -> DashboardOut:
    """Assemble the dashboard for ``viewer``.

    ``today`` and ``now`` are parameters rather than read from the clock so
    tests can pin them. ``today`` is a local date (due dates are calendar
    dates); ``now`` is naive UTC, matching ``Task.completed_at``.
    """
    teams = team_service.list_teams_for(db, viewer)
    team_names = {team.id: team.name for team in teams}

    projects = list(
        db.scalars(
            select(Project)
            .options(
                selectinload(Project.tasks).selectinload(Task.assignee),
                selectinload(Project.tasks).selectinload(Task.subtasks),
            )
            .where(Project.team_id.in_(team_names))
        )
    )
    tasks = [task for project in projects for task in project.tasks]
    clock = Clock(today=today, now=now)
    open_tasks = [task for task in tasks if _is_open(task)]
    open_subtasks = [s for task in tasks for s in task.subtasks if _is_open(s)]
    recent_cutoff = now - timedelta(days=RECENT_DAYS)
    meetings = meeting_service.upcoming_for(db, viewer, now=now)

    overview = Overview(
        teams=len(teams),
        active_projects=sum(1 for p in projects if p.status == ProjectStatus.ACTIVE),
        completed_projects=sum(1 for p in projects if p.status == ProjectStatus.COMPLETED),
        tasks=count_statuses(tasks),
        overdue=sum(1 for t in tasks if _is_overdue(t, clock)),
        due_soon=sum(1 for t in tasks if _is_due_soon(t, clock)),
        unassigned_open=sum(1 for t in open_tasks if t.assignee_id is None),
        completed_recently=sum(
            1 for t in tasks if t.completed_at is not None and t.completed_at >= recent_cutoff
        ),
        upcoming_meetings=len(meetings),
    )

    project_names = {project.id: project.name for project in projects}
    mine = [t for t in open_tasks if t.assignee_id == viewer.id]
    upcoming = sorted((t for t in mine if t.due_date is not None), key=_deadline_order)
    my_work = MyWork(
        open=len(mine),
        in_progress=sum(1 for t in mine if t.status == TaskStatus.IN_PROGRESS),
        overdue=sum(1 for t in mine if _is_overdue(t, clock)),
        due_soon=sum(1 for t in mine if _is_due_soon(t, clock)),
        upcoming=[
            TaskBrief(
                id=t.id,
                title=t.title,
                project_id=t.project_id,
                project_name=project_names[t.project_id],
                status=TaskStatus(t.status),
                due_date=t.due_date,
                due_at=as_utc(t.due_at),
            )
            for t in upcoming[:UPCOMING_LIMIT]
        ],
        **_my_subtasks(open_subtasks, viewer, project_names, clock),
    )

    project_stats = []
    for project in projects:
        counts = count_statuses(project.tasks)
        project_stats.append(
            ProjectStats(
                id=project.id,
                name=project.name,
                team_id=project.team_id,
                team_name=team_names[project.team_id],
                status=ProjectStatus(project.status),
                tasks=counts,
                percent_complete=_percent(counts.done, counts.total),
                overdue=sum(1 for t in project.tasks if _is_overdue(t, clock)),
            )
        )
    project_stats.sort(
        key=lambda p: (p.status != ProjectStatus.ACTIVE, p.team_name.lower(), p.name.lower(), p.id)
    )

    return DashboardOut(
        today=today,
        due_soon_days=DUE_SOON_DAYS,
        recent_days=RECENT_DAYS,
        overview=overview,
        my_work=my_work,
        projects=project_stats,
        workload=_workload(teams, open_tasks, open_subtasks, clock),
        meetings=[
            to_meeting_out(
                meeting, viewer, now=now, can_cancel=meeting_service.can_cancel(meeting, viewer)
            )
            for meeting in meetings[:MEETINGS_LIMIT]
        ],
    )


def _my_subtasks(
    open_subtasks: list[Subtask], viewer: User, project_names: dict[int, str], clock: Clock
) -> dict:
    """The ``MyWork`` fields about the open subtasks assigned to ``viewer``."""
    mine = [s for s in open_subtasks if s.assignee_id == viewer.id]
    dated = sorted((s for s in mine if s.due_date is not None), key=_deadline_order)
    return {
        "subtasks_open": len(mine),
        "subtasks_overdue": sum(1 for s in mine if _is_overdue(s, clock)),
        "subtasks_due_soon": sum(1 for s in mine if _is_due_soon(s, clock)),
        "upcoming_subtasks": [
            SubtaskBrief(
                id=s.id,
                title=s.title,
                task_id=s.task_id,
                task_title=s.task.title,
                project_id=s.task.project_id,
                project_name=project_names[s.task.project_id],
                status=TaskStatus(s.status),
                due_date=s.due_date,
                due_at=as_utc(s.due_at),
            )
            for s in dated[:UPCOMING_LIMIT]
        ],
    }


def _workload(
    teams: list[Team], open_tasks: list[Task], open_subtasks: list[Subtask], clock: Clock
) -> list[Workload]:
    """Open and overdue task counts, and open subtask counts, for every member of
    the visible teams.

    People with nothing assigned are included (with zeros) on purpose: on a
    workload chart, the person with no work is as important as the busiest.
    Sorted busiest first, then by name.
    """
    people: dict[int, User] = {}
    for team in teams:
        for member in team.members:
            people[member.id] = member

    rows = []
    for user_id, user in people.items():
        theirs = [t for t in open_tasks if t.assignee_id == user_id]
        rows.append(
            Workload(
                user=to_user_out(user),
                open=len(theirs),
                overdue=sum(1 for t in theirs if _is_overdue(t, clock)),
                open_subtasks=sum(1 for s in open_subtasks if s.assignee_id == user_id),
            )
        )
    rows.sort(key=lambda row: (-row.open, row.user.name.lower(), row.user.id))
    return rows
