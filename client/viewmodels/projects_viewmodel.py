"""The Projects screen, without any widgets (context.md goals #4-#6 and the Gantt chart).

The screen drills down: a team, then one of its projects, then (optionally) one
of the project's tasks. Every action -- create a project, save a task, tick a
subtask, add a dependency -- runs on a background thread and then reloads, in
the same job, everything on screen: who you are, your teams, the chosen team
with its members, its projects, the chosen project's tasks and Gantt chart, and
the chosen task with its subtasks. So the screen always shows what the server
has, the same way the Teams screen works.

While a job is running further actions are ignored, so a double-click can't
create a task twice.
"""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QObject, Signal

from client.api_client import ApiClient
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.session import Session
from shared.date_rules import DATE_RANGE_MESSAGE, date_in_range
from shared.text_rules import clean_display_text

MAX_PROJECT_NAME_LENGTH = 100
MAX_TITLE_LENGTH = 200
MAX_DESCRIPTION_LENGTH = 5000

#: Task statuses as the server spells them, with the labels the screen shows.
STATUS_LABELS: dict[str, str] = {"todo": "To do", "in_progress": "In progress", "done": "Done"}


def name_problem(name: str, *, what: str, limit: int) -> str | None:
    """A message if ``name`` is blank or too long, else None. Matches the server's
    rules, including ignoring invisible characters."""
    name = clean_display_text(name)
    if not name:
        return f"Enter a {what}."
    if len(name) > limit:
        return f"The {what} can be at most {limit} characters."
    return None


def task_fields_problem(fields: dict) -> str | None:
    """A message if the task form can't be saved, else None."""
    if problem := name_problem(fields.get("title", ""), what="task title", limit=MAX_TITLE_LENGTH):
        return problem
    if len(fields.get("description") or "") > MAX_DESCRIPTION_LENGTH:
        return f"The description can be at most {MAX_DESCRIPTION_LENGTH} characters."
    start, due = fields.get("start_date"), fields.get("due_date")
    if not (date_in_range(start) and date_in_range(due)):
        return DATE_RANGE_MESSAGE
    if start is not None and due is not None and start > due:
        return "The start date can't be after the due date."
    return None


def to_request(fields: dict) -> dict:
    """The task form's values in the form the API takes: trimmed text, ISO dates."""
    body = dict(fields)
    body["title"] = clean_display_text(body["title"])
    description = (body.get("description") or "").strip()
    body["description"] = description or None
    for key in ("start_date", "due_date"):
        value = body.get(key)
        body[key] = value.isoformat() if isinstance(value, date) else value
    return body


class ProjectsViewModel(QObject):
    """State and actions for the Projects tab. Every action reloads everything
    afterwards, so the screen always shows what the server has.
    """

    #: Your account as the server sees it now: {"id", "name", "email", "role"}.
    me_changed = Signal(dict)
    #: Everything on screen was reloaded (read the attributes below).
    changed = Signal()
    busy_changed = Signal(bool)
    #: The message to show, or "" to clear it.
    error_changed = Signal(str)

    _KEEP = object()

    def __init__(
        self,
        session: Session,
        runner: BackgroundRunner | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._runner = runner or BackgroundRunner(self)
        self._busy = False
        self._refresh_again = False
        self.me: dict = dict(session.user)
        self.teams: list[dict] = []
        #: The chosen team with its members (for the assignee list), or None.
        self.team: dict | None = None
        self.projects: list[dict] = []
        #: The chosen project as listed (with task counts), or None.
        self.project: dict | None = None
        self.tasks: list[dict] = []
        #: The chosen project's chart (server/schemas/gantt.py), or None.
        self.gantt: dict | None = None
        #: The chosen task with its subtasks, or None.
        self.task: dict | None = None
        #: False until the first load finishes, so the screen can say "Loading...".
        self.loaded = False

    # -------------------------------------------------------------- state

    @property
    def busy(self) -> bool:
        """True while a request is in flight (the view disables its buttons)."""
        return self._busy

    @property
    def team_id(self) -> int | None:
        """The chosen team's id, or None."""
        return self.team["id"] if self.team else None

    @property
    def project_id(self) -> int | None:
        """The chosen project's id, or None."""
        return self.project["id"] if self.project else None

    @property
    def task_id(self) -> int | None:
        """The chosen task's id, or None."""
        return self.task["id"] if self.task else None

    # ------------------------------------------------------------ choosing

    def refresh(self) -> None:
        """Reload everything; if a job is running, reload once it finishes."""
        if self._busy:
            self._refresh_again = True
            return
        self._run(None)

    def select_team(self, team_id: int | None) -> None:
        """Show another team's projects (its first project is chosen)."""
        if team_id != self.team_id:
            self._run(None, team=team_id, project=None, task=None)

    def select_project(self, project_id: int | None) -> None:
        """Show another project's tasks and chart."""
        if project_id != self.project_id:
            self._run(None, project=project_id, task=None)

    def select_task(self, task_id: int | None) -> None:
        """Open a task in the editor, or clear the editor for a new task (None)."""
        if task_id != self.task_id:
            self._run(None, task=task_id)

    # ------------------------------------------------------------ projects

    def create_project(self, name: str) -> None:
        """Create a project in the chosen team; it becomes the chosen project."""
        if self.team is None:
            return
        if problem := name_problem(name, what="project name", limit=MAX_PROJECT_NAME_LENGTH):
            self.error_changed.emit(problem)
            return
        team_id, name = self.team["id"], name.strip()
        self._run(lambda client: {"project": client.create_project(team_id, name)["id"]})

    def rename_project(self, name: str) -> None:
        """Rename the chosen project."""
        if self.project is None:
            return
        if problem := name_problem(name, what="project name", limit=MAX_PROJECT_NAME_LENGTH):
            self.error_changed.emit(problem)
            return
        project_id, name = self.project["id"], name.strip()
        self._run(lambda client: client.update_project(project_id, name=name))

    def set_project_completed(self, completed: bool) -> None:
        """Mark the chosen project completed, or reopen it."""
        if self.project is None:
            return
        project_id = self.project["id"]
        status = "completed" if completed else "active"
        self._run(lambda client: client.update_project(project_id, status=status))

    def delete_project(self) -> None:
        """Delete the chosen project and all its tasks."""
        if self.project is None:
            return
        project_id = self.project["id"]
        self._run(lambda client: client.delete_project(project_id), project=None, task=None)

    # --------------------------------------------------------------- tasks

    def create_task(self, fields: dict) -> None:
        """Create a task from the form's values; it becomes the chosen task.

        ``fields``: title, description, assignee_id, start_date, due_date
        (``datetime.date`` or None) and status.
        """
        if self.project is None:
            return
        if problem := task_fields_problem(fields):
            self.error_changed.emit(problem)
            return
        project_id, body = self.project["id"], to_request(fields)
        self._run(lambda client: {"task": client.create_task(project_id, **body)["id"]})

    def save_task(self, fields: dict) -> None:
        """Save the form's values over the chosen task."""
        if self.task is None:
            return
        if problem := task_fields_problem(fields):
            self.error_changed.emit(problem)
            return
        task_id, body = self.task["id"], to_request(fields)
        self._run(lambda client: client.update_task(task_id, **body))

    def set_task_status(self, task_id: int, status: str) -> None:
        """Change one task's status without opening it (e.g. from the task list)."""
        self._run(lambda client: client.update_task(task_id, status=status))

    def delete_task(self) -> None:
        """Delete the chosen task and its subtasks."""
        if self.task is None:
            return
        task_id = self.task["id"]
        self._run(lambda client: client.delete_task(task_id), task=None)

    # ------------------------------------------------------------ subtasks

    def add_subtask(self, title: str) -> None:
        """Add a subtask to the chosen task."""
        if self.task is None:
            return
        if problem := name_problem(title, what="subtask title", limit=MAX_TITLE_LENGTH):
            self.error_changed.emit(problem)
            return
        task_id, title = self.task["id"], clean_display_text(title)
        self._run(lambda client: client.create_subtask(task_id, title=title))

    def set_subtask_done(self, subtask_id: int, done: bool) -> None:
        """Tick or untick a subtask."""
        status = "done" if done else "todo"
        self._run(lambda client: client.update_subtask(subtask_id, status=status))

    def delete_subtask(self, subtask_id: int) -> None:
        """Delete a subtask."""
        self._run(lambda client: client.delete_subtask(subtask_id))

    # -------------------------------------------------------- dependencies

    def add_dependency(self, depends_on_id: int) -> None:
        """Make the chosen task wait on another task in the project."""
        if self.task is None:
            return
        task_id = self.task["id"]
        self._run(lambda client: client.add_dependency(task_id, depends_on_id))

    def remove_dependency(self, depends_on_id: int) -> None:
        """Stop the chosen task waiting on another task."""
        if self.task is None:
            return
        task_id = self.task["id"]
        self._run(lambda client: client.remove_dependency(task_id, depends_on_id))

    # ------------------------------------------------------------ plumbing

    def _run(
        self,
        action: Callable[[ApiClient], object] | None,
        *,
        team: object = _KEEP,
        project: object = _KEEP,
        task: object = _KEEP,
    ) -> None:
        """Do ``action`` (if any) then reload everything, on a background thread.

        ``team``/``project``/``task`` choose what is selected afterwards; by
        default the current choice stays if it still exists. ``action`` may
        return ``{"project": id}`` or ``{"task": id}`` to choose what it made.
        With no team chosen yet, the first team is; with no project, the first
        project is. A task is only open when one was chosen.
        """
        if self._busy:
            return
        client = self.session.client
        wanted = {
            "team": self.team_id if team is self._KEEP else team,
            "project": self.project_id if project is self._KEEP else project,
            "task": self.task_id if task is self._KEEP else task,
        }

        def job() -> dict:
            """Runs on the background thread: the action (if any), then the fresh data."""
            chosen = dict(wanted)
            if action is not None:
                result = action(client)
                if isinstance(result, dict):
                    chosen.update(result)
            me = client.me()
            teams = client.list_teams()
            data: dict = {
                "me": me,
                "teams": teams,
                "team": None,
                "projects": [],
                "project": None,
                "tasks": [],
                "gantt": None,
                "task": None,
            }
            team_ids = [t["id"] for t in teams]
            team_id = chosen["team"] if chosen["team"] in team_ids else None
            if team_id is None and team_ids:
                team_id = team_ids[0]
            if team_id is None:
                return data
            data["team"] = client.get_team(team_id)
            data["projects"] = projects = client.list_projects(team_id)
            by_id = {p["id"]: p for p in projects}
            project = by_id.get(chosen["project"]) or (projects[0] if projects else None)
            if project is None:
                return data
            data["project"] = project
            data["tasks"] = tasks = client.list_tasks(project["id"])
            data["gantt"] = client.get_gantt(project["id"])
            if chosen["task"] in {t["id"] for t in tasks}:
                data["task"] = client.get_task(chosen["task"])
            return data

        self.error_changed.emit("")
        self._set_busy(True)
        self._runner.run(job, on_success=self._loaded, on_error=self._failed)

    def _loaded(self, data: dict) -> None:
        """Main thread: store the fresh data and tell the view; run a refresh queued meanwhile."""
        self.loaded = True
        self._set_busy(False)
        if data["me"] != self.me:
            self.me = data["me"]
            self.session.user = data["me"]
            self.me_changed.emit(self.me)
        self.teams = data["teams"]
        self.team = data["team"]
        self.projects = data["projects"]
        self.project = data["project"]
        self.tasks = data["tasks"]
        self.gantt = data["gantt"]
        self.task = data["task"]
        self.changed.emit()
        self._run_queued_refresh()

    def _failed(self, message: str) -> None:
        """Main thread: show why the request failed; run a refresh queued meanwhile."""
        self._set_busy(False)
        self.error_changed.emit(message)
        self._run_queued_refresh()

    def _run_queued_refresh(self) -> None:
        """Run the one refresh asked for while busy, if any."""
        if self._refresh_again:
            self._refresh_again = False
            self.refresh()

    def _set_busy(self, busy: bool) -> None:
        """Record whether a request is in flight and tell the view."""
        self._busy = busy
        self.busy_changed.emit(busy)
