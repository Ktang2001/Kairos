"""Meeting rules shared by the FastAPI backend and the Qt client.

A meeting is a Jitsi call that someone (its host) starts or schedules from a
chat or a team; Kairos keeps the who/when and the replies, Jitsi carries the
call itself (see server/services/meeting_service.py). Used by the server's
request checks and the client's meeting dialog, so both agree.
"""

from datetime import timedelta
from enum import StrEnum


class MeetingResponse(StrEnum):
    """An invitee's reply, Teams-style. No reply yet is simply no row."""

    ACCEPTED = "accepted"
    TENTATIVE = "tentative"
    DECLINED = "declined"


class MeetingState(StrEnum):
    SCHEDULED = "scheduled"
    CANCELLED = "cancelled"


#: Labels for display in the Qt client.
MEETING_RESPONSE_DISPLAY_NAMES: dict[MeetingResponse, str] = {
    MeetingResponse.ACCEPTED: "Accepted",
    MeetingResponse.TENTATIVE: "Tentative",
    MeetingResponse.DECLINED: "Declined",
}

MAX_MEETING_TITLE_LENGTH = 200

DEFAULT_DURATION_MINUTES = 60
MIN_DURATION_MINUTES = 5
#: Eight hours: longer than any real meeting, short enough that a typo
#: (600 instead of 60) is caught rather than blocking the calendar for days.
MAX_DURATION_MINUTES = 480

#: A scheduled start this far in the past is still accepted, so a meeting set
#: for "now" in the dialog isn't refused because a minute passed while typing.
PAST_START_GRACE = timedelta(minutes=5)

#: The public Jitsi server. Hosts can point Kairos at another one (a
#: self-hosted Jitsi) in the server settings.
DEFAULT_JITSI_BASE_URL = "https://meet.jit.si"

# ------------------------------------------------------------------ reminders
#
# Everyone (except people who declined) is reminded at their own Profile
# default, plus at any times the host set for the meeting; a time that is in
# both goes off once (client/viewmodels/meeting_reminders.py).

#: Minutes before the start a host can add a reminder for everyone (0 = at
#: the start).
REMINDER_CHOICES: tuple[int, ...] = (0, 5, 10, 15, 30, 60, 120, 1440)

#: Minutes before the start each person can pick as their own default on the
#: Profile page (or Off).
PROFILE_REMINDER_CHOICES: tuple[int, ...] = (5, 10, 15, 30, 60)
DEFAULT_REMINDER_MINUTES = 15


def reminder_label(minutes: int) -> str:
    """ "At start", "5 minutes before", "1 hour before", "1 day before"."""
    if minutes == 0:
        return "At start"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days} day{'s' if days != 1 else ''} before"
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} hour{'s' if hours != 1 else ''} before"
    return f"{minutes} minute{'s' if minutes != 1 else ''} before"
