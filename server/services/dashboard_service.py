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

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlalchemy.orm import selectinload

from server.models.project import Project
from server.models.task import Task
from server.models.team import Team
from server.models.user import User
from server.schemas.auth import to_user_out
from server.schemas.dashboard import (
    DashboardOut,
    MyWork,
    Overview,
    ProjectStats,
    TaskBrief,
    Workload,
)
from server.schemas.project import count_statuses
from server.services import team_service
from shared.statuses import ProjectStatus, TaskStatus

#: "Due soon" means due between today and this many days from today, inclusive.
DUE_SOON_DAYS = 7
#: "Completed recently" means marked done within this many days.
RECENT_DAYS = 7
#: How many of the viewer's next deadlines ``my_work.upcoming`` lists.
UPCOMING_LIMIT = 5


def local_today() -> date:
    """Today's date on the hosting computer, in its own time zone.

    Due dates are calendar dates as people mean them ("due Friday"), so they
    are compared with the local date, not the UTC one -- in the evening in the
    Americas, UTC is already tomorrow.
    """
    return datetime.now(UTC).astimezone().date()


def _is_open(task: Task) -> bool:
    return task.status != TaskStatus.DONE


def _is_overdue(task: Task, today: date) -> bool:
    """Open and due *before* today. Due today is not overdue yet; no due date
    never is.
    """
    return _is_open(task) and task.due_date is not None and task.due_date < today


def _is_due_soon(task: Task, today: date) -> bool:
    return (
        _is_open(task)
        and task.due_date is not None
        and today <= task.due_date <= today + timedelta(days=DUE_SOON_DAYS)
    )


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
            .options(selectinload(Project.tasks).selectinload(Task.assignee))
            .where(Project.team_id.in_(team_names))
        )
    )
    tasks = [task for project in projects for task in project.tasks]
    open_tasks = [task for task in tasks if _is_open(task)]
    recent_cutoff = now - timedelta(days=RECENT_DAYS)

    overview = Overview(
        teams=len(teams),
        active_projects=sum(1 for p in projects if p.status == ProjectStatus.ACTIVE),
        completed_projects=sum(1 for p in projects if p.status == ProjectStatus.COMPLETED),
        tasks=count_statuses(tasks),
        overdue=sum(1 for t in tasks if _is_overdue(t, today)),
        due_soon=sum(1 for t in tasks if _is_due_soon(t, today)),
        unassigned_open=sum(1 for t in open_tasks if t.assignee_id is None),
        completed_recently=sum(
            1 for t in tasks if t.completed_at is not None and t.completed_at >= recent_cutoff
        ),
    )

    project_names = {project.id: project.name for project in projects}
    mine = [t for t in open_tasks if t.assignee_id == viewer.id]
    upcoming = sorted((t for t in mine if t.due_date is not None), key=lambda t: (t.due_date, t.id))
    my_work = MyWork(
        open=len(mine),
        in_progress=sum(1 for t in mine if t.status == TaskStatus.IN_PROGRESS),
        overdue=sum(1 for t in mine if _is_overdue(t, today)),
        due_soon=sum(1 for t in mine if _is_due_soon(t, today)),
        upcoming=[
            TaskBrief(
                id=t.id,
                title=t.title,
                project_id=t.project_id,
                project_name=project_names[t.project_id],
                status=TaskStatus(t.status),
                due_date=t.due_date,
            )
            for t in upcoming[:UPCOMING_LIMIT]
        ],
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
                overdue=sum(1 for t in project.tasks if _is_overdue(t, today)),
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
        workload=_workload(teams, open_tasks, today),
    )


def _workload(teams: list[Team], open_tasks: list[Task], today: date) -> list[Workload]:
    """Open and overdue task counts for every member of the visible teams.

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
                overdue=sum(1 for t in theirs if _is_overdue(t, today)),
            )
        )
    rows.sort(key=lambda row: (-row.open, row.user.name.lower(), row.user.id))
    return rows
