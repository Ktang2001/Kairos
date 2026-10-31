"""Tests for ``same_deadline`` (client/viewmodels/projects_viewmodel.py): a save
leaves an unchanged deadline out, so editing a title doesn't re-stamp its day."""

from datetime import UTC, datetime, timedelta, timezone

from client.viewmodels.projects_viewmodel import same_deadline

LOADED = {"due_date": "2026-11-04", "due_at": "2026-11-05T05:59:00Z"}


def test_the_same_moment_in_another_zone_is_the_same_deadline() -> None:
    chicago = timezone(timedelta(hours=-6))

    assert same_deadline(datetime(2026, 11, 4, 23, 59, tzinfo=chicago), LOADED)
    assert same_deadline(datetime(2026, 11, 5, 5, 59, tzinfo=UTC), LOADED)


def test_a_different_time_is_a_change() -> None:
    assert not same_deadline(datetime(2026, 11, 5, 6, 0, tzinfo=UTC), LOADED)


def test_clearing_is_a_change_and_none_to_none_is_not() -> None:
    assert not same_deadline(None, LOADED)
    assert same_deadline(None, {"due_date": None, "due_at": None})
    # A date with no time (older server) given one now: a change.
    assert not same_deadline(None, {"due_date": "2026-11-04", "due_at": None})


def test_nothing_loaded_is_always_a_change() -> None:
    assert not same_deadline(datetime(2026, 11, 5, 5, 59, tzinfo=UTC), None)
