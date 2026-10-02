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
from client.viewmodels.login_viewmodel import Session
from shared.account_rules import EMAIL_PATTERN

MAX_TEAM_NAME_LENGTH = 100


def team_name_problem(name: str) -> str | None:
    name = name.strip()
    if not name:
        return "Enter a team name."
    if len(name) > MAX_TEAM_NAME_LENGTH:
        return f"Team names can be at most {MAX_TEAM_NAME_LENGTH} characters."
    return None


class TeamsViewModel(QObject):
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
        self.me: dict = dict(session.user)
        self.teams: list[dict] = []
        self.team: dict | None = None
        #: False until the first load finishes, so the screen can say
        #: "Loading..." instead of "You're not on any teams yet".
        self.loaded = False

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def selected_id(self) -> int | None:
        return self.team["id"] if self.team else None

    # ------------------------------------------------------------- actions

    def refresh(self) -> None:
        self._run(None)

    def select_team(self, team_id: int | None) -> None:
        if team_id == self.selected_id:
            return
        self._run(None, select=team_id)

    def create_team(self, name: str) -> None:
        if problem := team_name_problem(name):
            self.error_changed.emit(problem)
            return
        name = name.strip()
        self._run(lambda client: client.create_team(name)["id"])

    def rename_team(self, name: str) -> None:
        if self.team is None:
            return
        if problem := team_name_problem(name):
            self.error_changed.emit(problem)
            return
        team_id, name = self.team["id"], name.strip()
        self._run(lambda client: client.rename_team(team_id, name))

    def delete_team(self) -> None:
        if self.team is None:
            return
        team_id = self.team["id"]
        self._run(lambda client: client.delete_team(team_id), select=None)

    def add_member(self, email: str) -> None:
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
        if self.team is None:
            return
        team_id = self.team["id"]
        self._run(lambda client: client.remove_member(team_id, user_id))

    def make_lead(self, user_id: int) -> None:
        if self.team is None:
            return
        team_id = self.team["id"]
        self._run(lambda client: client.change_lead(team_id, user_id))

    def leave_team(self) -> None:
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

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.error_changed.emit(message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
