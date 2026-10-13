"""Tests for the Gantt chart backend: start dates, task dependencies and
GET /projects/{id}/gantt.

Uses the shared fixtures from conftest.py: Lena (``lead``) leads team Alpha,
Max (``member``) is on it, Ada (``admin``) and Olga (``outsider``) are not.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from server.models.task import task_dependencies
from server.services import gantt_service
from tests.server.conftest import Account

D = date(2026, 11, 2)  # A fixed Monday, so tests don't depend on today's date.


def day(n: int) -> str:
    """``D`` plus ``n`` days, as the API writes dates."""
    return (D + timedelta(days=n)).isoformat()


@pytest.fixture
def project(client: TestClient, lead: Account, team: dict) -> dict:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Website"}, headers=lead.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def fixed_today(monkeypatch) -> date:
    """Pin the chart's "today" to ``D`` + 10 days."""
    today = D + timedelta(days=10)
    monkeypatch.setattr(gantt_service, "local_today", lambda: today)
    return today


def _add_task(client: TestClient, headers: dict, project_id: int, **fields) -> dict:
    response = client.post(
        f"/projects/{project_id}/tasks", json={"title": "Task", **fields}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def _depend(client: TestClient, headers: dict, task_id: int, on: int):
    return client.post(
        f"/tasks/{task_id}/dependencies", json={"depends_on_id": on}, headers=headers
    )


def _gantt(client: TestClient, headers: dict, project_id: int) -> dict:
    response = client.get(f"/projects/{project_id}/gantt", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------- start dates


def test_a_task_round_trips_its_start_and_due_dates(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _add_task(client, member.headers, project["id"], start_date=day(0), due_date=day(4))
    assert (task["start_date"], task["due_date"]) == (day(0), day(4))
    assert task["depends_on"] == []


def test_a_start_after_the_due_date_is_rejected_on_create(
    client: TestClient, member: Account, project: dict
) -> None:
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Backwards", "start_date": day(5), "due_date": day(1)},
        headers=member.headers,
    )
    assert response.status_code == 422


def test_start_and_due_on_the_same_day_is_allowed(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _add_task(client, member.headers, project["id"], start_date=day(3), due_date=day(3))
    assert task["start_date"] == task["due_date"] == day(3)


def test_a_patch_is_checked_against_the_stored_other_date(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _add_task(client, member.headers, project["id"], start_date=day(0), due_date=day(4))

    late_start = client.patch(
        f"/tasks/{task['id']}", json={"start_date": day(9)}, headers=member.headers
    )
    assert late_start.status_code == 422
    assert late_start.json()["detail"] == "The start date cannot be after the due date"

    early_due = client.patch(
        f"/tasks/{task['id']}", json={"due_date": day(-1)}, headers=member.headers
    )
    assert early_due.status_code == 422

    # Moving both together is fine, and nothing was changed by the refusals.
    moved = client.patch(
        f"/tasks/{task['id']}",
        json={"start_date": day(9), "due_date": day(12)},
        headers=member.headers,
    )
    assert moved.status_code == 200
    assert (moved.json()["start_date"], moved.json()["due_date"]) == (day(9), day(12))


def test_null_clears_the_start_date(client: TestClient, member: Account, project: dict) -> None:
    task = _add_task(client, member.headers, project["id"], start_date=day(0), due_date=day(4))
    response = client.patch(
        f"/tasks/{task['id']}", json={"start_date": None}, headers=member.headers
    )
    assert response.status_code == 200
    assert response.json()["start_date"] is None
    assert response.json()["due_date"] == day(4)


def test_subtasks_have_start_dates_with_the_same_rule(
    client: TestClient, member: Account, project: dict
) -> None:
    task = _add_task(client, member.headers, project["id"])
    created = client.post(
        f"/tasks/{task['id']}/subtasks",
        json={"title": "Step", "start_date": day(1), "due_date": day(2)},
        headers=member.headers,
    )
    assert created.status_code == 201
    subtask = created.json()["subtasks"][0]
    assert (subtask["start_date"], subtask["due_date"]) == (day(1), day(2))

    backwards = client.patch(
        f"/subtasks/{subtask['id']}", json={"start_date": day(5)}, headers=member.headers
    )
    assert backwards.status_code == 422

    bad_create = client.post(
        f"/tasks/{task['id']}/subtasks",
        json={"title": "Step", "start_date": day(5), "due_date": day(2)},
        headers=member.headers,
    )
    assert bad_create.status_code == 422


# --------------------------------------------------------------- dependencies


def test_any_member_can_add_a_dependency(
    client: TestClient, member: Account, project: dict
) -> None:
    design = _add_task(client, member.headers, project["id"], title="Design")
    build = _add_task(client, member.headers, project["id"], title="Build")

    response = _depend(client, member.headers, build["id"], design["id"])
    assert response.status_code == 201
    assert response.json()["depends_on"] == [design["id"]]

    listed = client.get(f"/projects/{project['id']}/tasks", headers=member.headers).json()
    assert {t["id"]: t["depends_on"] for t in listed} == {
        design["id"]: [],
        build["id"]: [design["id"]],
    }


def test_adding_the_same_dependency_twice_is_harmless(
    client: TestClient, member: Account, project: dict
) -> None:
    a = _add_task(client, member.headers, project["id"])
    b = _add_task(client, member.headers, project["id"])
    assert _depend(client, member.headers, b["id"], a["id"]).status_code == 201
    again = _depend(client, member.headers, b["id"], a["id"])
    assert again.status_code == 201
    assert again.json()["depends_on"] == [a["id"]]


def test_a_task_cannot_depend_on_itself(client: TestClient, member: Account, project: dict) -> None:
    a = _add_task(client, member.headers, project["id"])
    response = _depend(client, member.headers, a["id"], a["id"])
    assert response.status_code == 409


def test_a_loop_of_dependencies_is_refused(
    client: TestClient, member: Account, project: dict
) -> None:
    a, b, c = (_add_task(client, member.headers, project["id"]) for _ in range(3))
    assert _depend(client, member.headers, b["id"], a["id"]).status_code == 201
    assert _depend(client, member.headers, c["id"], b["id"]).status_code == 201

    # A -> C would close A -> C -> B -> A.
    response = _depend(client, member.headers, a["id"], c["id"])
    assert response.status_code == 409
    assert response.json()["detail"] == "That would make the tasks wait on each other in a loop"
    # Direct two-task loop too.
    assert _depend(client, member.headers, a["id"], b["id"]).status_code == 409

    task_a = client.get(f"/tasks/{a['id']}", headers=member.headers).json()
    assert task_a["depends_on"] == []


def test_a_diamond_is_not_a_loop(client: TestClient, member: Account, project: dict) -> None:
    """Two paths to the same task are fine: D waits on B and C, both wait on A."""
    a, b, c, d = (_add_task(client, member.headers, project["id"]) for _ in range(4))
    for task, on in ((b, a), (c, a), (d, b), (d, c)):
        assert _depend(client, member.headers, task["id"], on["id"]).status_code == 201
    assert sorted(client.get(f"/tasks/{d['id']}", headers=member.headers).json()["depends_on"]) == [
        b["id"],
        c["id"],
    ]


def test_a_dependency_must_be_in_the_same_project(
    client: TestClient, lead: Account, member: Account, team: dict, project: dict
) -> None:
    other_project = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Other"}, headers=lead.headers
    ).json()
    here = _add_task(client, member.headers, project["id"])
    there = _add_task(client, member.headers, other_project["id"])

    response = _depend(client, member.headers, here["id"], there["id"])
    assert response.status_code == 422
    # A task id that does not exist gets the same answer.
    assert _depend(client, member.headers, here["id"], 999_999).status_code == 422


def test_an_outsider_cannot_add_or_remove_dependencies(
    client: TestClient, member: Account, outsider: Account, project: dict
) -> None:
    a = _add_task(client, member.headers, project["id"])
    b = _add_task(client, member.headers, project["id"])
    assert _depend(client, outsider.headers, b["id"], a["id"]).status_code == 404

    _depend(client, member.headers, b["id"], a["id"])
    removed = client.delete(f"/tasks/{b['id']}/dependencies/{a['id']}", headers=outsider.headers)
    assert removed.status_code == 404


def test_a_dependency_can_be_removed(client: TestClient, member: Account, project: dict) -> None:
    a = _add_task(client, member.headers, project["id"])
    b = _add_task(client, member.headers, project["id"])
    _depend(client, member.headers, b["id"], a["id"])

    response = client.delete(f"/tasks/{b['id']}/dependencies/{a['id']}", headers=member.headers)
    assert response.status_code == 200
    assert response.json()["depends_on"] == []

    again = client.delete(f"/tasks/{b['id']}/dependencies/{a['id']}", headers=member.headers)
    assert again.status_code == 404


def test_deleting_a_task_removes_its_links_both_ways(
    client: TestClient,
    lead: Account,
    member: Account,
    project: dict,
    session_factory: sessionmaker[Session],
) -> None:
    a, b, c = (_add_task(client, member.headers, project["id"]) for _ in range(3))
    _depend(client, member.headers, b["id"], a["id"])
    _depend(client, member.headers, c["id"], b["id"])

    assert client.delete(f"/tasks/{b['id']}", headers=lead.headers).status_code == 204

    assert client.get(f"/tasks/{c['id']}", headers=member.headers).json()["depends_on"] == []
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(task_dependencies)) == 0


def test_deleting_a_project_leaves_no_dependency_rows(
    client: TestClient,
    lead: Account,
    member: Account,
    project: dict,
    session_factory: sessionmaker[Session],
) -> None:
    a = _add_task(client, member.headers, project["id"])
    b = _add_task(client, member.headers, project["id"])
    _depend(client, member.headers, b["id"], a["id"])

    assert client.delete(f"/projects/{project['id']}", headers=lead.headers).status_code == 204
    with session_factory() as db:
        assert db.scalar(select(func.count()).select_from(task_dependencies)) == 0


# ---------------------------------------------------------------- gantt chart


def test_an_empty_project_has_an_empty_chart(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    chart = _gantt(client, member.headers, project["id"])
    assert chart == {
        "project_id": project["id"],
        "project_name": "Website",
        "today": fixed_today.isoformat(),
        "range_start": None,
        "range_end": None,
        "rows": [],
        "unscheduled": [],
        "conflicts": [],
    }


def test_rows_are_in_start_order_with_subtasks_under_their_task(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    pid = project["id"]
    later = _add_task(
        client, member.headers, pid, title="Later", start_date=day(5), due_date=day(9)
    )
    first = _add_task(
        client, member.headers, pid, title="First", start_date=day(0), due_date=day(3)
    )
    client.post(
        f"/tasks/{first['id']}/subtasks",
        json={"title": "Step", "start_date": day(1), "due_date": day(2)},
        headers=member.headers,
    )

    chart = _gantt(client, member.headers, pid)
    assert [(r["kind"], r["title"]) for r in chart["rows"]] == [
        ("task", "First"),
        ("subtask", "Step"),
        ("task", "Later"),
    ]
    assert chart["rows"][1]["parent_task_id"] == first["id"]
    assert chart["rows"][2]["id"] == later["id"]
    assert (chart["range_start"], chart["range_end"]) == (day(0), day(9))


def test_a_task_with_one_date_is_a_one_day_estimated_bar(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    pid = project["id"]
    _add_task(client, member.headers, pid, title="Due only", due_date=day(20))
    _add_task(client, member.headers, pid, title="Start only", start_date=day(15))
    _add_task(client, member.headers, pid, title="Both", start_date=day(11), due_date=day(12))

    rows = {r["title"]: r for r in _gantt(client, member.headers, pid)["rows"]}
    assert (rows["Due only"]["start"], rows["Due only"]["end"]) == (day(20), day(20))
    assert (rows["Start only"]["start"], rows["Start only"]["end"]) == (day(15), day(15))
    assert rows["Due only"]["estimated"] and rows["Start only"]["estimated"]
    assert not rows["Both"]["estimated"]


def test_undated_tasks_and_subtasks_are_listed_as_unscheduled(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    pid = project["id"]
    undated = _add_task(client, member.headers, pid, title="Someday")
    dated = _add_task(
        client, member.headers, pid, title="Dated", start_date=day(0), due_date=day(1)
    )
    client.post(f"/tasks/{dated['id']}/subtasks", json={"title": "Loose"}, headers=member.headers)

    chart = _gantt(client, member.headers, pid)
    assert [r["title"] for r in chart["rows"]] == ["Dated"]
    assert [(r["title"], r["start"], r["end"]) for r in chart["unscheduled"]] == [
        ("Loose", None, None),
        ("Someday", None, None),
    ]
    assert chart["unscheduled"][1]["id"] == undated["id"]


def test_progress_follows_status_and_subtasks(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    pid = project["id"]
    dates = {"start_date": day(11), "due_date": day(12)}
    _add_task(client, member.headers, pid, title="Todo", **dates)
    _add_task(client, member.headers, pid, title="Doing", status="in_progress", **dates)
    _add_task(client, member.headers, pid, title="Done", status="done", **dates)
    split = _add_task(client, member.headers, pid, title="Split", status="in_progress", **dates)
    for status in ("done", "todo", "todo"):
        client.post(
            f"/tasks/{split['id']}/subtasks",
            json={"title": "Part", "status": status},
            headers=member.headers,
        )

    rows = {r["title"]: r for r in _gantt(client, member.headers, pid)["rows"]}
    assert rows["Todo"]["progress"] == 0
    assert rows["Doing"]["progress"] == gantt_service.IN_PROGRESS_WITHOUT_SUBTASKS
    assert rows["Done"]["progress"] == 100
    assert rows["Split"]["progress"] == 33


def test_all_subtasks_done_but_task_open_is_not_shown_as_finished(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    task = _add_task(client, member.headers, project["id"], start_date=day(11), due_date=day(12))
    client.post(
        f"/tasks/{task['id']}/subtasks",
        json={"title": "Only", "status": "done"},
        headers=member.headers,
    )
    row = _gantt(client, member.headers, project["id"])["rows"][0]
    assert row["progress"] == 99


def test_overdue_means_past_the_end_and_not_done(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    pid = project["id"]
    _add_task(client, member.headers, pid, title="Late", start_date=day(0), due_date=day(9))
    _add_task(client, member.headers, pid, title="Late but done", due_date=day(9), status="done")
    _add_task(client, member.headers, pid, title="Due today", due_date=day(10))

    rows = {r["title"]: r for r in _gantt(client, member.headers, pid)["rows"]}
    assert rows["Late"]["overdue"] is True
    assert rows["Late but done"]["overdue"] is False
    assert rows["Due today"]["overdue"] is False


def test_dependencies_and_out_of_order_dates_are_reported(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    pid = project["id"]
    design = _add_task(
        client, member.headers, pid, title="Design", start_date=day(0), due_date=day(4)
    )
    build = _add_task(
        client, member.headers, pid, title="Build", start_date=day(3), due_date=day(8)
    )
    test = _add_task(client, member.headers, pid, title="Test", start_date=day(9), due_date=day(10))
    _depend(client, member.headers, build["id"], design["id"])
    _depend(client, member.headers, test["id"], build["id"])

    chart = _gantt(client, member.headers, pid)
    rows = {r["title"]: r for r in chart["rows"]}
    assert rows["Build"]["depends_on"] == [design["id"]]
    assert rows["Test"]["depends_on"] == [build["id"]]
    # Build starts (day 3) before Design ends (day 4); Test is correctly after Build.
    assert chart["conflicts"] == [{"task_id": build["id"], "depends_on_id": design["id"]}]

    # Once Design is done, the overlap no longer matters.
    client.patch(f"/tasks/{design['id']}", json={"status": "done"}, headers=member.headers)
    assert _gantt(client, member.headers, pid)["conflicts"] == []


def test_assignees_are_shown_on_the_bars(
    client: TestClient, member: Account, project: dict, fixed_today: date
) -> None:
    _add_task(
        client,
        member.headers,
        project["id"],
        assignee_id=member.id,
        start_date=day(11),
        due_date=day(12),
    )
    row = _gantt(client, member.headers, project["id"])["rows"][0]
    assert row["assignee"]["id"] == member.id
    assert row["assignee"]["name"] == "Max"


def test_admins_can_see_any_chart_and_outsiders_cannot(
    client: TestClient, admin: Account, outsider: Account, project: dict
) -> None:
    assert client.get(f"/projects/{project['id']}/gantt", headers=admin.headers).status_code == 200
    assert (
        client.get(f"/projects/{project['id']}/gantt", headers=outsider.headers).status_code == 404
    )
    assert client.get("/projects/999999/gantt", headers=admin.headers).status_code == 404


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/projects/1/gantt"),
        ("post", "/tasks/1/dependencies"),
        ("delete", "/tasks/1/dependencies/2"),
    ],
)
def test_every_gantt_route_requires_login(client: TestClient, method: str, url: str) -> None:
    assert client.request(method, url).status_code == 401


def test_local_today_is_a_date() -> None:
    assert isinstance(gantt_service.local_today(), date)


def test_bar_dates_covers_every_combination() -> None:
    assert gantt_service.bar_dates(D, D + timedelta(days=2)) == (D, D + timedelta(days=2), False)
    assert gantt_service.bar_dates(D, None) == (D, D, True)
    assert gantt_service.bar_dates(None, D) == (D, D, True)
    assert gantt_service.bar_dates(None, None) == (None, None, False)
