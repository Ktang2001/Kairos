"""Tests for GET /dashboard (context.md goal #7).

Uses the shared fixtures from conftest.py: Lena (``lead``) leads team Alpha,
Max (``member``) is on it, Ada (``admin``) and Olga (``outsider``) are not.

Due dates are written relative to ``local_today()``, the same clock the route
uses, so the boundary tests (yesterday / today / +7 / +8 days) hold whatever
day the suite runs on.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from server.models.task import Task
from server.services.auth_service import utcnow
from server.services.dashboard_service import (
    DUE_SOON_DAYS,
    RECENT_DAYS,
    UPCOMING_LIMIT,
    local_today,
)
from tests.server.conftest import Account

TODAY = local_today()


def _days(n: int) -> str:
    return (TODAY + timedelta(days=n)).isoformat()


@pytest.fixture
def project(client: TestClient, lead: Account, team: dict) -> dict:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Website"}, headers=lead.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def add_task(client: TestClient, member: Account) -> Callable[..., dict]:
    def _add(project_id: int, title: str = "t", **fields) -> dict:
        response = client.post(
            f"/projects/{project_id}/tasks",
            json={"title": title, **fields},
            headers=member.headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _add


def _dashboard(client: TestClient, account: Account) -> dict:
    response = client.get("/dashboard", headers=account.headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------- empty


def test_a_user_with_no_teams_gets_an_all_zero_dashboard(
    client: TestClient, outsider: Account
) -> None:
    body = _dashboard(client, outsider)
    assert body["today"] == TODAY.isoformat()
    assert body["due_soon_days"] == DUE_SOON_DAYS
    assert body["recent_days"] == RECENT_DAYS
    assert body["overview"] == {
        "teams": 0,
        "active_projects": 0,
        "completed_projects": 0,
        "tasks": {"todo": 0, "in_progress": 0, "done": 0, "total": 0},
        "overdue": 0,
        "due_soon": 0,
        "unassigned_open": 0,
        "completed_recently": 0,
    }
    assert body["my_work"] == {
        "open": 0,
        "in_progress": 0,
        "overdue": 0,
        "due_soon": 0,
        "upcoming": [],
    }
    assert body["projects"] == []
    assert body["workload"] == []


def test_a_project_with_no_tasks_is_zero_percent_not_an_error(
    client: TestClient, lead: Account, project: dict
) -> None:
    [stats] = _dashboard(client, lead)["projects"]
    assert stats["percent_complete"] == 0.0
    assert stats["tasks"]["total"] == 0


def test_the_dashboard_requires_login(client: TestClient) -> None:
    assert client.get("/dashboard").status_code == 401


# ------------------------------------------------------------------- overview


def test_overview_counts_teams_projects_and_task_statuses(
    client: TestClient, lead: Account, team: dict, project: dict, add_task: Callable
) -> None:
    done_project = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Old"}, headers=lead.headers
    ).json()
    client.patch(
        f"/projects/{done_project['id']}", json={"status": "completed"}, headers=lead.headers
    )

    for status in ("todo", "todo", "in_progress", "done"):
        add_task(project["id"], status=status)

    overview = _dashboard(client, lead)["overview"]
    assert overview["teams"] == 1
    assert (overview["active_projects"], overview["completed_projects"]) == (1, 1)
    assert overview["tasks"] == {"todo": 2, "in_progress": 1, "done": 1, "total": 4}


@pytest.mark.parametrize(
    ("due_in_days", "overdue", "due_soon"),
    [
        (-30, True, False),
        (-1, True, False),
        (0, False, True),  # due today is not overdue yet
        (DUE_SOON_DAYS, False, True),  # the last day of the window counts
        (DUE_SOON_DAYS + 1, False, False),
        (365, False, False),
    ],
    ids=["month-ago", "yesterday", "today", "last-day-of-window", "day-after-window", "next-year"],
)
def test_overdue_and_due_soon_boundaries(
    client: TestClient,
    lead: Account,
    project: dict,
    add_task: Callable,
    due_in_days: int,
    overdue: bool,
    due_soon: bool,
) -> None:
    add_task(project["id"], due_date=_days(due_in_days))
    overview = _dashboard(client, lead)["overview"]
    assert (overview["overdue"], overview["due_soon"]) == (int(overdue), int(due_soon))


def test_done_and_undated_tasks_are_never_overdue_or_due_soon(
    client: TestClient, lead: Account, project: dict, add_task: Callable
) -> None:
    add_task(project["id"], due_date=_days(-5), status="done")
    add_task(project["id"], due_date=_days(2), status="done")
    add_task(project["id"])  # no due date
    overview = _dashboard(client, lead)["overview"]
    assert (overview["overdue"], overview["due_soon"]) == (0, 0)


def test_unassigned_open_ignores_assigned_and_done_tasks(
    client: TestClient, lead: Account, member: Account, project: dict, add_task: Callable
) -> None:
    add_task(project["id"])  # counts
    add_task(project["id"], status="in_progress")  # counts
    add_task(project["id"], assignee_id=member.id)
    add_task(project["id"], status="done")
    assert _dashboard(client, lead)["overview"]["unassigned_open"] == 2


def test_completed_recently_uses_the_completion_time(
    client: TestClient,
    lead: Account,
    project: dict,
    add_task: Callable,
    session_factory: sessionmaker[Session],
) -> None:
    recent = add_task(project["id"], status="done")
    old = add_task(project["id"], status="done")
    reopened = add_task(project["id"], status="done")
    client.patch(f"/tasks/{reopened['id']}", json={"status": "todo"}, headers=lead.headers)

    db = session_factory()
    try:
        db.execute(
            update(Task)
            .where(Task.id == old["id"])
            .values(completed_at=utcnow() - timedelta(days=RECENT_DAYS + 1))
        )
        db.commit()
    finally:
        db.close()

    assert recent  # completed just now
    assert _dashboard(client, lead)["overview"]["completed_recently"] == 1


# -------------------------------------------------------------------- my work


def test_my_work_counts_only_my_open_tasks(
    client: TestClient, lead: Account, member: Account, project: dict, add_task: Callable
) -> None:
    add_task(project["id"], assignee_id=member.id)
    add_task(project["id"], assignee_id=member.id, status="in_progress", due_date=_days(-1))
    add_task(project["id"], assignee_id=member.id, due_date=_days(3))
    add_task(project["id"], assignee_id=member.id, status="done")
    add_task(project["id"], assignee_id=lead.id)

    mine = _dashboard(client, member)["my_work"]
    assert mine["open"] == 3
    assert mine["in_progress"] == 1
    assert mine["overdue"] == 1
    assert mine["due_soon"] == 1


def test_upcoming_lists_my_next_deadlines_soonest_first_and_is_capped(
    client: TestClient, member: Account, project: dict, add_task: Callable
) -> None:
    for offset in (9, -2, 4, 1, 30, 2, 15):
        add_task(project["id"], f"due{offset:+d}", assignee_id=member.id, due_date=_days(offset))
    add_task(project["id"], "undated", assignee_id=member.id)
    add_task(project["id"], "finished", assignee_id=member.id, due_date=_days(0), status="done")

    upcoming = _dashboard(client, member)["my_work"]["upcoming"]
    assert len(upcoming) == UPCOMING_LIMIT
    assert [t["title"] for t in upcoming] == ["due-2", "due+1", "due+2", "due+4", "due+9"]
    assert upcoming[0]["project_name"] == "Website"
    assert upcoming[0]["project_id"] == project["id"]


# ------------------------------------------------------------------- projects


def test_project_stats_report_progress_and_overdue(
    client: TestClient, lead: Account, team: dict, project: dict, add_task: Callable
) -> None:
    add_task(project["id"], status="done")
    add_task(project["id"], status="done")
    add_task(project["id"], due_date=_days(-1))

    [stats] = _dashboard(client, lead)["projects"]
    assert stats["name"] == "Website"
    assert stats["team_id"] == team["id"]
    assert stats["team_name"] == "Alpha"
    assert stats["status"] == "active"
    assert stats["percent_complete"] == 66.7
    assert stats["overdue"] == 1


def test_a_fully_done_project_is_one_hundred_percent(
    client: TestClient, lead: Account, project: dict, add_task: Callable
) -> None:
    add_task(project["id"], status="done")
    assert _dashboard(client, lead)["projects"][0]["percent_complete"] == 100.0


def test_projects_are_listed_active_first(
    client: TestClient, lead: Account, team: dict, project: dict
) -> None:
    old = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Archive"}, headers=lead.headers
    ).json()
    client.patch(f"/projects/{old['id']}", json={"status": "completed"}, headers=lead.headers)
    client.post(f"/teams/{team['id']}/projects", json={"name": "Blog"}, headers=lead.headers)

    names = [p["name"] for p in _dashboard(client, lead)["projects"]]
    assert names == ["Blog", "Website", "Archive"]


# ------------------------------------------------------------------- workload


def test_workload_lists_every_member_busiest_first_including_idle_people(
    client: TestClient, lead: Account, member: Account, project: dict, add_task: Callable
) -> None:
    add_task(project["id"], assignee_id=member.id)
    add_task(project["id"], assignee_id=member.id, due_date=_days(-3))
    add_task(project["id"], assignee_id=member.id, status="done")

    workload = _dashboard(client, lead)["workload"]
    assert [(w["user"]["id"], w["open"], w["overdue"]) for w in workload] == [
        (member.id, 2, 1),
        (lead.id, 0, 0),
    ]
    assert "password" not in str(workload)


# ----------------------------------------------------------------- visibility


def test_the_dashboard_only_shows_teams_the_viewer_is_on(
    client: TestClient,
    member: Account,
    make_account: Callable[..., Account],
    project: dict,
    add_task: Callable,
) -> None:
    add_task(project["id"])

    beta_lead = make_account("Bea", "project_lead")
    beta = client.post("/teams", json={"name": "Beta"}, headers=beta_lead.headers).json()
    beta_project = client.post(
        f"/teams/{beta['id']}/projects", json={"name": "Secret"}, headers=beta_lead.headers
    ).json()
    client.post(
        f"/projects/{beta_project['id']}/tasks",
        json={"title": "hidden", "due_date": _days(-1)},
        headers=beta_lead.headers,
    )

    body = _dashboard(client, member)
    assert body["overview"]["teams"] == 1
    assert body["overview"]["tasks"]["total"] == 1
    assert body["overview"]["overdue"] == 0
    assert [p["name"] for p in body["projects"]] == ["Website"]
    assert beta_lead.id not in [w["user"]["id"] for w in body["workload"]]
    assert "Secret" not in str(body) and "hidden" not in str(body)


def test_an_admin_sees_every_team(
    client: TestClient,
    admin: Account,
    make_account: Callable[..., Account],
    project: dict,
    add_task: Callable,
) -> None:
    add_task(project["id"])
    beta_lead = make_account("Bea", "project_lead")
    beta = client.post("/teams", json={"name": "Beta"}, headers=beta_lead.headers).json()
    client.post(f"/teams/{beta['id']}/projects", json={"name": "Secret"}, headers=beta_lead.headers)

    body = _dashboard(client, admin)
    assert body["overview"]["teams"] == 2
    assert sorted(p["name"] for p in body["projects"]) == ["Secret", "Website"]
    # The admin is on neither team, so has no work of their own.
    assert body["my_work"]["open"] == 0


def test_a_person_on_two_teams_appears_once_in_workload(
    client: TestClient,
    admin: Account,
    member: Account,
    make_account: Callable[..., Account],
    team: dict,
) -> None:
    beta_lead = make_account("Bea", "project_lead")
    beta = client.post("/teams", json={"name": "Beta"}, headers=beta_lead.headers).json()
    client.post(
        f"/teams/{beta['id']}/members", json={"email": member.email}, headers=beta_lead.headers
    )

    ids = [w["user"]["id"] for w in _dashboard(client, admin)["workload"]]
    assert ids.count(member.id) == 1


def test_leaving_a_team_removes_its_work_from_your_dashboard(
    client: TestClient, member: Account, team: dict, project: dict, add_task: Callable
) -> None:
    add_task(project["id"], assignee_id=member.id, due_date=_days(-1))
    client.delete(f"/teams/{team['id']}/members/{member.id}", headers=member.headers)

    body = _dashboard(client, member)
    assert body["overview"]["teams"] == 0
    assert body["my_work"]["open"] == 0
