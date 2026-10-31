"""Meeting actions shared by the Chat, Dashboard, Teams and Profile pages.

Start or schedule, reply, cancel and join, each on a background thread. One
instance is shared by the whole signed-in window (AppShell), so a reply made
on the dashboard reaches the chat's card too: every change emits
``meeting_changed`` and the pages showing meetings reload.

Takes the ``ApiClient`` rather than a ``Session`` because the chat pages,
which predate ``Session``, use it too.

Joining asks the server for the link every time (a cancelled or finished
meeting is refused there), checks it is https, adds your Profile options and
opens it in the browser.
"""

from collections.abc import Callable, Sequence
from datetime import datetime

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtGui import QDesktopServices

from client.api_client import ApiClient
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.meeting_preferences import MeetingPreferences, is_safe_meeting_url

#: Shown instead of opening a link that isn't https (see is_safe_meeting_url).
UNSAFE_LINK_MESSAGE = "The meeting link isn't a secure https:// address, so it wasn't opened."
#: Shown when the system can't open the browser.
NO_BROWSER_MESSAGE = "Couldn't open your web browser for the meeting."


def _open_in_browser(url: str) -> bool:
    return QDesktopServices.openUrl(QUrl(url))


class MeetingsViewModel(QObject):
    """Meeting actions for the signed-in user. Results arrive as signals."""

    #: A meeting was created or changed: the server's MeetingOut.
    meeting_changed = Signal(dict)
    #: The meetings in one chat: (conversation_id, [MeetingOut, ...]).
    chat_meetings_loaded = Signal(int, list)
    busy_changed = Signal(bool)
    #: The message to show, or "" to clear it.
    error_changed = Signal(str)

    def __init__(
        self,
        client: ApiClient,
        preferences: MeetingPreferences | None = None,
        runner: BackgroundRunner | None = None,
        display_name: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.preferences = preferences or MeetingPreferences()
        #: Your Kairos name: what Jitsi shows unless the Profile page sets another.
        self.display_name = display_name
        self._runner = runner or BackgroundRunner(self)
        self._busy = 0
        #: Opens a link in the browser. Replaced in tests so none ever opens.
        self.open_url: Callable[[str], bool] = _open_in_browser

    @property
    def busy(self) -> bool:
        """True while any meeting request is in flight."""
        return self._busy > 0

    # -------------------------------------------------------------- actions

    def create_in_chat(
        self,
        conversation_id: int,
        *,
        title: str,
        starts_at: datetime | None,
        duration_minutes: int,
        client_token: str,
        reminder_minutes: Sequence[int] = (),
    ) -> None:
        """Start (``starts_at`` None) or schedule a meeting in a chat.

        An instant meeting is opened in the browser for you straight away.
        ``reminder_minutes`` are the reminders you set for everyone invited.
        """
        fields = self._fields(title, starts_at, duration_minutes, client_token, reminder_minutes)
        client = self.client
        self._run(
            lambda: client.create_chat_meeting(conversation_id, **fields),
            join_after=starts_at is None,
        )

    def create_for_team(
        self,
        team_id: int,
        *,
        title: str,
        starts_at: datetime | None,
        duration_minutes: int,
        client_token: str,
        reminder_minutes: Sequence[int] = (),
    ) -> None:
        """Start or schedule a meeting for a team, held in its team chat."""
        fields = self._fields(title, starts_at, duration_minutes, client_token, reminder_minutes)
        client = self.client
        self._run(
            lambda: client.create_team_meeting(team_id, **fields), join_after=starts_at is None
        )

    def respond(self, meeting_id: int, response: str) -> None:
        """Accept, tentatively accept or decline."""
        client = self.client
        self._run(lambda: client.respond_to_meeting(meeting_id, response))

    def edit(
        self,
        meeting_id: int,
        *,
        title: str,
        starts_at: datetime,
        duration_minutes: int,
        reminder_minutes: Sequence[int] = (),
    ) -> None:
        """Change a meeting you host (or, as an admin, a team meeting). Moving it
        to another time clears everyone's replies (the server does that)."""
        if starts_at.tzinfo is None:
            starts_at = starts_at.astimezone()
        changes = {
            "title": title,
            "starts_at": starts_at.isoformat(),
            "duration_minutes": duration_minutes,
            "reminder_minutes": sorted(set(reminder_minutes)),
        }
        client = self.client
        self._run(lambda: client.update_meeting(meeting_id, **changes))

    def cancel(self, meeting_id: int) -> None:
        """Cancel a meeting you host (or, as an admin, a team meeting)."""
        client = self.client
        self._run(lambda: client.cancel_meeting(meeting_id))

    def join(self, meeting_id: int) -> None:
        """Ask the server for the link and open it in the browser."""
        client = self.client
        self._start()
        self._runner.run(
            lambda: client.meeting_join_link(meeting_id),
            on_success=self._open_meeting,
            on_error=self._failed,
        )

    def load_chat_meetings(self, conversation_id: int) -> None:
        """Fetch a chat's meetings, for its cards (answer: ``chat_meetings_loaded``).

        Not counted as busy: the chat polls this every few seconds, and the
        buttons shouldn't flicker each time.
        """
        client = self.client
        self._runner.run(
            lambda: client.list_chat_meetings(conversation_id),
            on_success=lambda meetings: self.chat_meetings_loaded.emit(conversation_id, meetings),
            on_error=self.error_changed.emit,
        )

    def load_teams(self, on_ready: Callable[[list[dict]], None]) -> None:
        """Fetch your teams for the "which team?" picker, then call ``on_ready``."""
        client = self.client
        self._start()

        def ready(teams: list[dict]) -> None:
            self._finish()
            on_ready(teams)

        self._runner.run(client.list_teams, on_success=ready, on_error=self._failed)

    def open_jitsi_home(self) -> None:
        """Open the server's Jitsi site, so you can sign in there ahead of time."""
        client = self.client
        self._start()
        self._runner.run(
            lambda: client.get_server_info()["jitsi_base_url"],
            on_success=self._open_link,
            on_error=self._failed,
        )

    # ------------------------------------------------------------- internals

    @staticmethod
    def _fields(
        title: str,
        starts_at: datetime | None,
        duration_minutes: int,
        client_token: str,
        reminder_minutes: Sequence[int],
    ) -> dict:
        """The request body. ``starts_at`` must be time-zone aware (the server refuses
        a bare local time), so a naive one is taken as this computer's local time."""
        if starts_at is not None and starts_at.tzinfo is None:
            starts_at = starts_at.astimezone()
        return {
            "title": title,
            "starts_at": starts_at.isoformat() if starts_at is not None else None,
            "duration_minutes": duration_minutes,
            "client_token": client_token,
            "reminder_minutes": sorted(set(reminder_minutes)),
        }

    def _run(self, action: Callable[[], dict], *, join_after: bool = False) -> None:
        """Run a create/reply/cancel request; on success announce the meeting
        (and, for an instant meeting, join it)."""
        self._start()

        def done(meeting: dict) -> None:
            self._finish()
            self.error_changed.emit("")
            self.meeting_changed.emit(meeting)
            if join_after:
                self.join(meeting["id"])

        self._runner.run(action, on_success=done, on_error=self._failed)

    def _open_meeting(self, url: str) -> None:
        """Main thread: add your Profile options to the link and open it."""
        if not is_safe_meeting_url(url):
            self._failed(UNSAFE_LINK_MESSAGE)
            return
        self._open_link(self.preferences.join_url(url, self.display_name))

    def _open_link(self, url: str) -> None:
        """Main thread: open an https link in the browser."""
        self._finish()
        if not is_safe_meeting_url(url):
            self.error_changed.emit(UNSAFE_LINK_MESSAGE)
            return
        if self.open_url(url):
            self.error_changed.emit("")
        else:
            self.error_changed.emit(NO_BROWSER_MESSAGE)

    def _failed(self, message: str) -> None:
        self._finish()
        self.error_changed.emit(message)

    def _start(self) -> None:
        self._busy += 1
        if self._busy == 1:
            self.busy_changed.emit(True)

    def _finish(self) -> None:
        if self._busy == 0:
            return
        self._busy -= 1
        if self._busy == 0:
            self.busy_changed.emit(False)
