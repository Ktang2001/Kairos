"""Meeting reminders, worked out on this computer while Kairos is open.

Who: everyone a meeting is visible to, except people who declined it -- the
host, anyone who accepted or said tentative, and anyone who hasn't replied.

When: at your own default (Profile page, e.g. 15 minutes before) plus at
every time the host set for the meeting. The same time in both goes off
once. The host isn't reminded of anything that was due before they made the
meeting -- an instant meeting starts as it is made, and they are already
joining it -- while invitees still get "Starting now", which is how they
hear about it. If several have come due since the last check -- Kairos was just
opened ten minutes before a meeting with 60- and 15-minute reminders -- only
the latest shows, so nobody gets a burst of pop-ups for one meeting.

Shown reminders are remembered on this computer (MeetingPreferences), so
restarting Kairos or signing in again doesn't repeat them. Nothing reminds
you while Kairos is closed: the server doesn't push anything.

Times are compared as moments (UTC with offsets), so it doesn't matter which
time zone the host or this computer is in.
"""

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

from client.api_client import ApiClient
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.meeting_preferences import MeetingPreferences
from shared.meetings import MeetingResponse, MeetingState

#: How often the list of upcoming meetings is re-fetched from the server.
REFRESH_MS = 60_000
#: How often the fetched list is checked for reminders that have come due.
CHECK_MS = 15_000


def _utc_now() -> datetime:
    return datetime.now(UTC)


def reminder_key(server: str, meeting: dict, fire_at: datetime) -> str:
    """Identifies one reminder: which server, which meeting, at what moment.

    Keyed by the moment rather than by "15 minutes before", so a host's
    15-minute reminder and your own 15-minute default are the same reminder.
    """
    return f"{server}|{meeting['id']}|{fire_at.astimezone(UTC).isoformat()}"


def due_reminders(
    meetings: list[dict],
    *,
    now: datetime,
    default_minutes: int | None,
    fired: set[str],
    server: str,
) -> tuple[list[dict], list[str]]:
    """Which meetings to remind about now, and which reminders that uses up.

    ``now`` is time-zone aware. Returns the meetings to show (at most one
    reminder each) and the keys of every reminder that came due, including
    earlier ones skipped in favour of the latest.
    """
    to_show: list[dict] = []
    used: list[str] = []
    for meeting in meetings:
        if meeting["state"] == MeetingState.CANCELLED or meeting["has_ended"]:
            continue
        if meeting.get("my_response") == MeetingResponse.DECLINED:
            continue
        start = datetime.fromisoformat(meeting["starts_at"])
        end = datetime.fromisoformat(meeting["ends_at"])
        if now >= end:
            continue
        leads = set(meeting.get("reminder_minutes") or [])
        if default_minutes is not None:
            leads.add(default_minutes)
        created = (
            datetime.fromisoformat(meeting["created_at"]) if meeting.get("created_at") else None
        )
        show = False
        for lead in leads:
            fire_at = start - timedelta(minutes=lead)
            key = reminder_key(server, meeting, fire_at)
            if fire_at > now or key in fired or key in used:
                continue
            used.append(key)
            if not (meeting.get("is_host") and created is not None and fire_at < created):
                show = True
        if show:
            to_show.append(meeting)
    return to_show, used


def reminder_message(meeting: dict, now: datetime) -> str:
    """ "Starts in 15 minutes", "Starts in 1 hour 5 minutes", "Starting now",
    "Started 3 minutes ago" -- worked out from the start time, not from which
    reminder fired, so it is right even when shown late."""
    seconds = (datetime.fromisoformat(meeting["starts_at"]) - now).total_seconds()
    if abs(seconds) < 60:
        return "Starting now"
    minutes = math.ceil(seconds / 60) if seconds > 0 else math.floor(-seconds / 60)
    hours, rest = divmod(minutes, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
    if rest or not hours:
        parts.append(f"{rest} minute{'s' if rest != 1 else ''}")
    span = " ".join(parts)
    return f"Starts in {span}" if seconds > 0 else f"Started {span} ago"


class MeetingReminders(QObject):
    """Fetches your upcoming meetings now and then, and says when a reminder is due."""

    #: A reminder to show: (MeetingOut, message such as "Starts in 15 minutes").
    reminder_due = Signal(dict, str)

    def __init__(
        self,
        client: ApiClient,
        preferences: MeetingPreferences,
        runner: BackgroundRunner | None = None,
        clock: Callable[[], datetime] = _utc_now,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self.preferences = preferences
        self._runner = runner or BackgroundRunner(self)
        #: Time-zone aware "now". Replaced in tests.
        self.clock = clock
        #: The upcoming meetings last fetched.
        self.meetings: list[dict] = []
        self._loading = False

        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(REFRESH_MS)
        self._refresh_timer.timeout.connect(self.refresh)
        self._check_timer = QTimer(self)
        self._check_timer.setInterval(CHECK_MS)
        self._check_timer.timeout.connect(self.check)

    def start(self) -> None:
        """Begin fetching and checking (call once signed in)."""
        self._refresh_timer.start()
        self._check_timer.start()
        self.refresh()

    def stop(self) -> None:
        """Stop for good (signed out, or the window closed)."""
        self._refresh_timer.stop()
        self._check_timer.stop()

    def refresh(self) -> None:
        """Re-fetch upcoming meetings in the background, then check them."""
        if self._loading:
            return
        self._loading = True
        client = self.client
        self._runner.run(client.list_upcoming_meetings, self._loaded, self._failed)

    def check(self) -> None:
        """Announce every reminder that has come due since the last check."""
        now = self.clock()
        to_show, used = due_reminders(
            self.meetings,
            now=now,
            default_minutes=self.preferences.reminder_minutes,
            fired=set(self.preferences.fired_reminders()),
            # Per account as well as per server: two people who sign in on the
            # same computer each get their own reminders.
            server=f"{self.client.base_url}#{getattr(self.client, 'user_id', None)}",
        )
        if used:
            self.preferences.remember_fired(used)
        for meeting in to_show:
            self.reminder_due.emit(meeting, reminder_message(meeting, now))

    def _loaded(self, meetings: list[dict]) -> None:
        self._loading = False
        self.meetings = meetings
        self.check()

    def _failed(self, _message: str) -> None:
        # Background polling: a missed fetch is tried again next time. The
        # pages already show connection problems; reminders stay quiet.
        self._loading = False
