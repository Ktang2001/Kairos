"""The Teams screen, without any widgets (context.md goal #1).

Every action -- create, rename, delete, add/remove member, hand over the
lead, leave -- runs on a background thread and then reloads, in the same
job, who you are (your role may have been changed by an admin), your teams,
and the selected team. So after any action the screen shows the server's
real state, never a guess.

While a job is running further actions are ignored, so a double-click can't
create a team twice.
"""

from collections.abc import Callable

from PySide6.QtCore import QObject, Signal

from client.api_client import ApiClient
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.session import Session
from shared.account_rules import EMAIL_PATTERN

MAX_TEAM_NAME_LENGTH = 100


def team_name_problem(name: str) -> str | None:
    """A message if the team name is blank or too long, else None. Matches the server's rule."""
    name = name.strip()
    if not name:
        return "Enter a team name."
    if len(name) > MAX_TEAM_NAME_LENGTH:
        return f"Team names can be at most {MAX_TEAM_NAME_LENGTH} characters."
    return None


class TeamsViewModel(QObject):
    """State and actions for the Teams tab: your teams, the selected one, and the changes you may
    make. Every action reloads everything afterwards, so the screen always shows what the server
    has.
    """

    #: Your account as the server sees it now: {"id", "name", "email", "role"}.
    me_changed = Signal(dict)
    #: The list of teams you can see (summaries).
    teams_changed = Signal(list)
    #: The selected team with its members, or None when nothing is selected.
    team_changed = Signal(object)
    busy_changed = Signal(bool)
    #: The message to show, or "" to clear it.
    error_changed = Signal(str)

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
        #: A refresh was asked for while busy; it runs when the current job ends.
        self._refresh_again = False
        self.me: dict = dict(session.user)
        self.teams: list[dict] = []
        self.team: dict | None = None
        #: False until the first load finishes, so the screen can say
        #: "Loading..." instead of "You're not on any teams yet".
        self.loaded = False

    @property
    def busy(self) -> bool:
        """True while a request is in flight (the view disables its buttons)."""
        return self._busy

    @property
    def selected_id(self) -> int | None:
        """The id of the team shown on the right, or None."""
        return self.team["id"] if self.team else None

    # ------------------------------------------------------------- actions

    def refresh(self) -> None:
        """Reload everything; if a job is running, reload once it finishes.

        Queued rather than dropped: Retry (or the timer) pressed while a slow
        request is still timing out must not be silently ignored. Repeated
        calls while busy collapse into a single follow-up refresh.
        """
        if self._busy:
            self._refresh_again = True
            return
        self._run(None)

    def select_team(self, team_id: int | None) -> None:
        """Show a different team (loads its members)."""
        if team_id == self.selected_id:
            return
        self._run(None, select=team_id)

    def create_team(self, name: str) -> None:
        """Create a team after checking the name; it becomes the selected team."""
        if problem := team_name_problem(name):
            self.error_changed.emit(problem)
            return
        name = name.strip()
        self._run(lambda client: client.create_team(name)["id"])

    def rename_team(self, name: str) -> None:
        """Rename the selected team after checking the name."""
        if self.team is None:
            return
        if problem := team_name_problem(name):
            self.error_changed.emit(problem)
            return
        team_id, name = self.team["id"], name.strip()
        self._run(lambda client: client.rename_team(team_id, name))

    def delete_team(self) -> None:
        """Delete the selected team."""
        if self.team is None:
            return
        team_id = self.team["id"]
        self._run(lambda client: client.delete_team(team_id), select=None)

    def add_member(self, email: str) -> None:
        """Add someone to the selected team by email, after checking it looks like one."""
        if self.team is None:
            return
        email = email.strip()
        if not email:
            self.error_changed.emit("Enter the email of the person to add.")
            return
        if not EMAIL_PATTERN.match(email):
            self.error_changed.emit("That doesn't look like an email address.")
            return
        team_id = self.team["id"]
        self._run(lambda client: client.add_member(team_id, email))

    def remove_member(self, user_id: int) -> None:
        """Remove a member from the selected team."""
        if self.team is None:
            return
        team_id = self.team["id"]
        self._run(lambda client: client.remove_member(team_id, user_id))

    def make_lead(self, user_id: int) -> None:
        """Hand the selected team's lead to another member."""
        if self.team is None:
            return
        team_id = self.team["id"]
        self._run(lambda client: client.change_lead(team_id, user_id))

    def leave_team(self) -> None:
        """Remove yourself from the selected team."""
        if self.team is None:
            return
        team_id, my_id = self.team["id"], self.me["id"]
        self._run(lambda client: client.remove_member(team_id, my_id), select=None)

    # ------------------------------------------------------------ plumbing

    _KEEP = object()

    def _run(self, action: Callable[[ApiClient], object] | None, select: object = _KEEP) -> None:
        """Do ``action`` (if any) then reload everything, on a background thread.

        ``action`` may return a team id to select it (used by create_team).
        ``select`` overrides which team is selected afterwards; by default the
        current one stays selected if it still exists.
        """
        if self._busy:
            return
        client = self.session.client
        wanted = self.selected_id if select is self._KEEP else select

        def job() -> tuple[dict, list[dict], dict | None]:
            """Runs on the background thread: the action (if any), then the fresh data."""
            chosen = wanted
            if action is not None:
                result = action(client)
                if isinstance(result, int):
                    chosen = result
            me = client.me()
            teams = client.list_teams()
            detail = None
            if chosen is not None and any(t["id"] == chosen for t in teams):
                detail = client.get_team(chosen)
            return me, teams, detail

        self.error_changed.emit("")
        self._set_busy(True)
        self._runner.run(job, on_success=self._loaded, on_error=self._failed)

    def _loaded(self, result: tuple[dict, list[dict], dict | None]) -> None:
        """Main thread: store the fresh data and tell the view; run a refresh queued meanwhile."""
        me, teams, detail = result
        self.loaded = True
        self._set_busy(False)
        if me != self.me:
            self.me = me
            self.session.user = me
            self.me_changed.emit(me)
        self.teams = teams
        self.team = detail
        self.teams_changed.emit(teams)
        self.team_changed.emit(detail)
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
