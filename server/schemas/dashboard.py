"""Response shape of GET /dashboard (context.md goal #7)."""

from datetime import date

from pydantic import BaseModel

from server.schemas.auth import UserOut
from server.schemas.project import StatusCounts
from shared.statuses import ProjectStatus, TaskStatus


class TaskBrief(BaseModel):
    """Just enough of a task to show in a "coming up" list and link to it."""

    id: int
    title: str
    project_id: int
    project_name: str
    status: TaskStatus
    due_date: date | None


class Overview(BaseModel):
    """Totals across every team the viewer can see."""

    teams: int
    active_projects: int
    completed_projects: int
    tasks: StatusCounts
    #: Not done, and the due date is before today.
    overdue: int
    #: Not done, and due between today and ``DUE_SOON_DAYS`` from today, inclusive.
    due_soon: int
    #: Not done, and nobody is assigned.
    unassigned_open: int
    #: Marked done within the last ``RECENT_DAYS`` days.
    completed_recently: int


class MyWork(BaseModel):
    """The viewer's own open tasks."""

    open: int
    in_progress: int
    overdue: int
    due_soon: int
    #: The viewer's open tasks with a due date, soonest first (overdue first).
    upcoming: list[TaskBrief]


class ProjectStats(BaseModel):
    id: int
    name: str
    team_id: int
    team_name: str
    status: ProjectStatus
    tasks: StatusCounts
    #: Done / total * 100, to one decimal place. 0.0 for a project with no tasks.
    percent_complete: float
    overdue: int


class Workload(BaseModel):
    """One person's open tasks across the teams the viewer can see."""

    user: UserOut
    open: int
    overdue: int


class DashboardOut(BaseModel):
    #: The date every "overdue"/"due soon" figure was measured against: the
    #: hosting computer's local date, so clients can show it.
    today: date
    due_soon_days: int
    recent_days: int
    overview: Overview
    my_work: MyWork
    projects: list[ProjectStats]
    workload: list[Workload]
