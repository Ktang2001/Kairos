"""Tests for client/views/time_text.py: deadlines and times in this computer's zone."""

from datetime import UTC, date, datetime, timedelta

from client.views.time_text import due_day, due_moment, is_past_due, show_due, zone_name

#: 05:59 UTC on Nov 5 = 11:59 PM on Nov 4 in Chicago (UTC-6).
DUE_UTC = "2026-11-05T05:59:00Z"


def _here(utc_text: str) -> datetime:
    return datetime.fromisoformat(utc_text).astimezone()


def test_an_exact_deadline_is_shown_in_this_computers_zone() -> None:
    item = {"due_date": "2026-11-04", "due_at": DUE_UTC}
    here = _here(DUE_UTC)
    clock = here.strftime("%I:%M %p").lstrip("0")

    assert show_due(item) == f"{here:%b %d, %Y} {clock} {zone_name(here)}"
    assert show_due(item, year=False) == f"{here:%b %d} {clock} {zone_name(here)}"
    assert due_moment(item) == here
    # The day here, which may differ from the setter's day near midnight.
    assert due_day(item) == here.date()


def test_a_date_only_deadline_from_an_older_server_shows_the_date() -> None:
    item = {"due_date": "2026-11-04"}

    assert show_due(item) == "Nov 04, 2026"
    assert show_due(item, year=False) == "Nov 04"
    assert due_moment(item) is None
    assert due_day(item) == date(2026, 11, 4)


def test_no_deadline_shows_nothing() -> None:
    assert show_due({"due_date": None, "due_at": None}) == ""
    assert due_day({"due_date": None}) is None


def test_past_due_is_the_exact_moment() -> None:
    item = {"due_date": "2026-11-04", "due_at": DUE_UTC}
    moment = datetime.fromisoformat(DUE_UTC)
    today = date(2026, 11, 4)

    assert not is_past_due(item, moment - timedelta(minutes=1), today)
    assert is_past_due(item, moment + timedelta(minutes=1), today)


def test_past_due_without_a_time_is_the_day_before_today() -> None:
    item = {"due_date": "2026-11-04"}
    now = datetime(2026, 11, 4, 23, 0, tzinfo=UTC)

    assert not is_past_due(item, now, date(2026, 11, 4))
    assert is_past_due(item, now, date(2026, 11, 5))
    assert not is_past_due({"due_date": None}, now, date(2026, 11, 5))
