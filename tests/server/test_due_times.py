"""Tests for exact deadlines: a task's or subtask's ``due_at``.

The rules under test (server/schemas/task.py, server/services/task_service.py):

* ``due_at`` carries the setter's offset; ``due_date`` becomes its date in
  *their* time zone, and responses give ``due_at`` back in UTC;
* a client that sends only ``due_date`` gets 11:59 PM that day in the host
  computer's time zone;
* a time without a zone, or a ``due_date`` that isn't ``due_at``'s date, is
  refused; null clears both;
* "overdue" (dashboard and Gantt chart) is the exact moment passing, not the
  day ending.
"""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from fastapi.testclient import TestClient

from server.services.dashboard_service import local_today
from tests.server.conftest import Account


@pytest.fixture
def project(client: TestClient, lead: Account, team: dict) -> dict:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Website"}, headers=lead.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create(client: TestClient, account: Account, project: dict, **fields) -> dict:
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Launch", "assignee_id": account.id, **fields},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _patch(client: TestClient, account: Account, task_id: int, **fields) -> dict:
    response = client.patch(f"/tasks/{task_id}", json=fields, headers=account.headers)
    assert response.status_code == 200, response.text
    return response.json()


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _end_of_day_here(day: date) -> datetime:
    """11:59 PM on ``day`` in this (the host) computer's zone, as aware UTC."""
    return datetime.combine(day, time(23, 59)).astimezone().astimezone(UTC)


# ------------------------------------------------------------- setting it


def test_a_deadline_keeps_its_exact_time_and_the_setters_day(
    client: TestClient, member: Account, project: dict
) -> None:
    # 11:59 PM on Nov 4 in Chicago (UTC-6) is 05:59 on Nov 5 in UTC.
    task = _create(client, member, project, due_at="2026-11-04T23:59:00-06:00")

    assert task["due_date"] == "2026-11-04"
    assert _utc(task["due_at"]) == datetime(2026, 11, 5, 5, 59, tzinfo=UTC)
    assert _utc(task["due_at"]).utcoffset() == timedelta(0)


def test_the_day_is_the_setters_even_past_utc_midnight(
    client: TestClient, member: Account, project: dict
) -> None:
    # 00:30 on Nov 5 in Tokyo (UTC+9) is still Nov 4 in UTC: the day is Tokyo's.
    task = _create(client, member, project, due_at="2026-11-05T00:30:00+09:00")

    assert task["due_date"] == "2026-11-05"
    assert _utc(task["due_at"]) == datetime(2026, 11, 4, 15, 30, tzinfo=UTC)


def test_only_a_date_means_end_of_that_day_on_the_host(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _create(client, member, project, due_date="2026-11-04")

    assert task["due_date"] == "2026-11-04"
    assert _utc(task["due_at"]) == _end_of_day_here(date(2026, 11, 4))


def test_no_deadline_means_neither(client: TestClient, member: Account, project: dict) -> None:
    task = _create(client, member, project)

    assert task["due_date"] is None and task["due_at"] is None


@pytest.mark.parametrize(
    "fields",
    [
        {"due_at": "2026-11-04T23:59:00"},  # no time zone: whose 11:59 PM?
        {"due_at": "2026-11-04T23:59:00-06:00", "due_date": "2026-11-05"},
        {"due_at": "2300-01-01T00:00:00+00:00"},
        {"due_at": "not a time"},
        {"due_at": "2026-11-04T23:59:00-06:00", "start_date": "2026-11-05"},
    ],
)
def test_bad_deadlines_are_refused(
    client: TestClient, member: Account, project: dict, fields: dict
) -> None:
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Launch", **fields},
        headers=member.headers,
    )

    assert response.status_code == 422, response.text


def test_a_matching_due_date_alongside_due_at_is_fine(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _create(
        client, member, project, due_at="2026-11-04T17:00:00-06:00", due_date="2026-11-04"
    )

    assert _utc(task["due_at"]) == datetime(2026, 11, 4, 23, 0, tzinfo=UTC)


# ------------------------------------------------------------- changing it


def test_changing_the_time_moves_the_day_with_it(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _create(client, member, project, due_at="2026-11-04T23:59:00-06:00")

    changed = _patch(client, member, task["id"], due_at="2026-11-06T09:00:00-06:00")

    assert changed["due_date"] == "2026-11-06"
    assert _utc(changed["due_at"]) == datetime(2026, 11, 6, 15, 0, tzinfo=UTC)


def test_changing_only_the_date_resets_the_time_to_end_of_day(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _create(client, member, project, due_at="2026-11-04T09:00:00-06:00")

    changed = _patch(client, member, task["id"], due_date="2026-11-07")

    assert changed["due_date"] == "2026-11-07"
    assert _utc(changed["due_at"]) == _end_of_day_here(date(2026, 11, 7))


@pytest.mark.parametrize("cleared", [{"due_at": None}, {"due_date": None}])
def test_clearing_either_clears_the_deadline(
    client: TestClient, member: Account, project: dict, cleared: dict
) -> None:
    task = _create(client, member, project, due_at="2026-11-04T23:59:00-06:00")

    changed = _patch(client, member, task["id"], **cleared)

    assert changed["due_date"] is None and changed["due_at"] is None


def test_other_edits_leave_the_deadline_alone(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _create(client, member, project, due_at="2026-11-04T23:59:00-06:00")

    changed = _patch(client, member, task["id"], title="Launch v2")

    assert changed["due_at"] == task["due_at"]
    assert changed["due_date"] == "2026-11-04"


def test_a_patch_cannot_put_the_deadline_before_the_start(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _create(client, member, project, start_date="2026-11-04")

    response = client.patch(
        f"/tasks/{task['id']}",
        json={"due_at": "2026-11-03T23:59:00-06:00"},
        headers=member.headers,
    )

    assert response.status_code == 422, response.text


def test_tasks_due_the_same_day_are_listed_by_time(
    client: TestClient, member: Account, project: dict
) -> None:
    _create(client, member, project, title="Evening", due_at="2026-11-04T18:00:00+00:00")
    _create(client, member, project, title="Morning", due_at="2026-11-04T09:00:00+00:00")

    tasks = client.get(f"/projects/{project['id']}/tasks", headers=member.headers).json()

    assert [t["title"] for t in tasks] == ["Morning", "Evening"]


# ------------------------------------------------------------- subtasks


def test_subtasks_have_exact_deadlines_too(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _create(client, member, project)

    response = client.post(
        f"/tasks/{task['id']}/subtasks",
        json={"title": "Copy", "due_at": "2026-11-04T23:59:00-06:00"},
        headers=member.headers,
    )
    assert response.status_code == 201, response.text
    subtask = response.json()["subtasks"][0]
    assert subtask["due_date"] == "2026-11-04"
    assert _utc(subtask["due_at"]) == datetime(2026, 11, 5, 5, 59, tzinfo=UTC)

    response = client.patch(
        f"/subtasks/{subtask['id']}",
        json={"due_at": "2026-11-05T12:00:00+00:00"},
        headers=member.headers,
    )
    assert response.status_code == 200, response.text
    changed = response.json()["subtasks"][0]
    assert changed["due_date"] == "2026-11-05"
    assert _utc(changed["due_at"]) == datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


# ------------------------------------------------------------- overdue


def _in(**delta) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def test_a_deadline_an_hour_ago_is_overdue_even_today(
    client: TestClient, member: Account, project: dict
) -> None:
    _create(client, member, project, due_at=_in(minutes=-1))

    mine = client.get("/dashboard", headers=member.headers).json()["my_work"]

    assert mine["overdue"] == 1
    assert mine["due_soon"] == 0


def test_a_deadline_later_today_is_due_soon_not_overdue(
    client: TestClient, member: Account, project: dict
) -> None:
    # Within the next hour, but no later than the end of the host's day.
    end_of_today = _end_of_day_here(local_today())
    due = min(datetime.now(UTC) + timedelta(hours=1), end_of_today)
    if due <= datetime.now(UTC) + timedelta(seconds=30):
        pytest.skip("too close to midnight on this computer to test 'later today'")
    _create(client, member, project, due_at=due.astimezone().isoformat())

    mine = client.get("/dashboard", headers=member.headers).json()["my_work"]

    assert mine["overdue"] == 0
    assert mine["due_soon"] == 1
    assert mine["upcoming"][0]["due_at"] is not None


def test_the_gantt_chart_flags_a_deadline_that_just_passed(
    client: TestClient, member: Account, project: dict
) -> None:
    _create(client, member, project, title="Late", due_at=_in(minutes=-1))
    _create(client, member, project, title="Not yet", due_at=_in(days=2))

    rows = client.get(f"/projects/{project['id']}/gantt", headers=member.headers).json()["rows"]

    assert {r["title"]: r["overdue"] for r in rows} == {"Late": True, "Not yet": False}


def test_a_done_task_is_never_overdue(client: TestClient, member: Account, project: dict) -> None:
    _create(client, member, project, due_at=_in(days=-3), status="done")

    assert client.get("/dashboard", headers=member.headers).json()["overview"]["overdue"] == 0


# ------------------------------------------------------------- unchanged saves


def test_resending_the_same_date_keeps_the_picked_time(
    client: TestClient, member: Account, project: dict
) -> None:
    # An older client knows only dates and sends the date back with every save.
    task = _create(client, member, project, due_at="2026-11-04T09:00:00-06:00")

    changed = _patch(client, member, task["id"], title="Launch v2", due_date="2026-11-04")

    assert changed["due_at"] == task["due_at"]


# ------------------------------------------------------------- the viewer's date


def test_due_soon_counts_from_the_viewers_own_date(
    client: TestClient, member: Account, project: dict
) -> None:
    today = local_today()
    _create(client, member, project, due_date=(today + timedelta(days=8)).isoformat())

    def due_soon(day: date) -> int:
        response = client.get(
            "/dashboard", params={"today": day.isoformat()}, headers=member.headers
        )
        assert response.status_code == 200, response.text
        assert response.json()["today"] == day.isoformat()
        return response.json()["my_work"]["due_soon"]

    # Eight days from the host's today; seven from a viewer already on tomorrow.
    utc_today = datetime.now(UTC).date()
    if abs((today + timedelta(days=1) - utc_today).days) > 1:
        pytest.skip("this computer's zone puts tomorrow out of any zone's reach")
    assert due_soon(today) == 0
    assert due_soon(today + timedelta(days=1)) == 1


@pytest.mark.parametrize("days", [-3, 2, 400])
def test_a_viewer_date_far_from_the_servers_is_refused(
    client: TestClient, member: Account, project: dict, days: int
) -> None:
    far = (datetime.now(UTC).date() + timedelta(days=days)).isoformat()

    for url in ("/dashboard", f"/projects/{project['id']}/gantt"):
        response = client.get(url, params={"today": far}, headers=member.headers)
        assert response.status_code == 422, (url, response.text)
        assert "clock" in response.json()["detail"]


def test_the_gantt_today_line_is_the_viewers_date(
    client: TestClient, member: Account, project: dict
) -> None:
    viewer_day = datetime.now(UTC).date() + timedelta(days=1)

    chart = client.get(
        f"/projects/{project['id']}/gantt",
        params={"today": viewer_day.isoformat()},
        headers=member.headers,
    ).json()

    assert chart["today"] == viewer_day.isoformat()
