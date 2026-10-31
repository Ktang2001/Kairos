"""Response shape for GET /projects/{id}/gantt.

One response holds everything a Gantt chart draws: a row per task (and per
dated subtask, right under its task), the date range to size the time axis,
today's date for the "now" line, the dependency arrows, and any arrow whose
order the dates break.
"""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from server.schemas.user import UserOut
from shared.statuses import TaskStatus


class GanttRow(BaseModel):
    """One bar on the chart.

    ``start``/``end`` are the bar's ends, both inclusive. A task with only one
    of its two dates is drawn as a one-day bar on that date, with
    ``estimated`` true so the client can draw it differently. Rows with
    neither date are not drawn; they are listed in ``GanttOut.unscheduled``
    with ``start``/``end`` null.
    """

    kind: Literal["task", "subtask"]
    id: int
    #: The parent task's id for a subtask; null for a task.
    parent_task_id: int | None
    title: str
    status: TaskStatus
    assignee: UserOut | None
    start: date | None
    end: date | None
    estimated: bool
    #: 0-100. See ``gantt_service.task_progress``.
    progress: int
    #: The exact deadline (UTC), if it has one, for the hover text: the bar
    #: itself is drawn by whole days.
    due_at: datetime | None = None
    #: The deadline has passed and the work is not done.
    overdue: bool
    #: Tasks this one waits on (the chart's arrows point from them to it).
    #: Always empty for subtasks.
    depends_on: list[int]


class ScheduleConflict(BaseModel):
    """A dependency whose dates are out of order: ``task_id`` is scheduled to
    start on or before the day ``depends_on_id`` is scheduled to end."""

    task_id: int
    depends_on_id: int


class GanttOut(BaseModel):
    """The whole chart for one project."""

    project_id: int
    project_name: str
    #: Today on the hosting computer, for the chart's "now" line.
    today: date
    #: Earliest start and latest end over the drawn rows; null when nothing is scheduled.
    range_start: date | None
    range_end: date | None
    #: Tasks in start order (undated ones last), each followed by its dated subtasks.
    rows: list[GanttRow]
    unscheduled: list[GanttRow]
    conflicts: list[ScheduleConflict]
