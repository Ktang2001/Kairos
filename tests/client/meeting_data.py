"""A server-shaped meeting (MeetingOut, server/schemas/meeting.py) for client tests."""

from datetime import UTC, datetime, timedelta


def make_meeting(starts: datetime | None = None, **overrides) -> dict:
    """A scheduled team meeting (tomorrow at 15:00 UTC unless ``starts`` says
    otherwise), an hour long, that someone else hosts and you haven't replied
    to. Override any other field by name."""
    if starts is None:
        today = datetime.now(UTC).replace(hour=15, minute=0, second=0, microsecond=0)
        starts = today + timedelta(days=1)
    duration = overrides.get("duration_minutes", 60)
    meeting = {
        "id": 7,
        "conversation_id": 3,
        "team_id": 1,
        "team_name": "Alpha",
        "title": "Stand-up",
        "starts_at": starts.isoformat(),
        "ends_at": (starts + timedelta(minutes=duration)).isoformat(),
        "duration_minutes": duration,
        "host": {"id": 2, "name": "Lena", "email": "lena@example.com", "role": "project_lead"},
        "state": "scheduled",
        "cancelled_at": None,
        "created_at": (starts - timedelta(days=1)).isoformat(),
        "reminder_minutes": [],
        "has_ended": False,
        "is_host": False,
        "can_cancel": False,
        "my_response": None,
        "responses": [],
        "counts": {"accepted": 0, "tentative": 0, "declined": 0, "no_response": 2},
    }
    meeting.update(overrides)
    return meeting
