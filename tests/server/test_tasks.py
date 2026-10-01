"""Tests for tasks and subtasks (context.md goals #4-6).

Uses the shared fixtures from conftest.py: Lena (``lead``) leads team Alpha,
Max (``member``) is on it, Ada (``admin``) and Olga (``outsider``) are not.
"""

from collections.abc import Callable
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from server.schemas.task import MAX_TASK_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH
from server.services.auth_service import utcnow
from server.services.dashboard_service import local_today
from tests.server.conftest import Account


@pytest.fixture
def project(client: TestClient, lead: Account, team: dict) -> dict:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Website"}, headers=lead.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def task(client: TestClient, member: Account, project: dict) -> dict:
    """A task Max created, assigned to Max."""
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Write homepage", "assignee_id": member.id},
        headers=member.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _patch(client: TestClient, headers: dict, task_id: int, **fields) -> dict:
    response = client.patch(f"/tasks/{task_id}", json=fields, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------- create


def test_any_member_can_create_a_task_with_sensible_defaults(
    client: TestClient, member: Account, project: dict
) -> None:
    response = client.post(
        f"/projects/{project['id']}/tasks", json={"title": "  Logo  "}, headers=member.headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Logo"
    assert body["status"] == "todo"
    assert body["assignee"] is None
    assert body["due_date"] is None
    assert body["completed_at"] is None
    assert body["subtasks"] == []
    assert (body["subtasks_done"], body["subtasks_total"]) == (0, 0)


def test_a_task_can_be_created_with_every_field(
    client: TestClient, member: Account, lead: Account, project: dict
) -> None:
    body = client.post(
        f"/projects/{project['id']}/tasks",
        json={
            "title": "Logo",
            "description": "SVG please",
            "assignee_id": lead.id,
            "due_date": "2030-01-31",
            "status": "in_progress",
        },
        headers=member.headers,
    ).json()
    assert body["description"] == "SVG please"
    assert body["assignee"]["id"] == lead.id
    assert body["due_date"] == "2030-01-31"
    assert body["status"] == "in_progress"


def test_a_task_created_as_done_records_when(
    client: TestClient, member: Account, project: dict
) -> None:
    body = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Already done", "status": "done"},
        headers=member.headers,
    ).json()
    assert body["completed_at"] is not None


def test_a_past_due_date_is_allowed(client: TestClient, member: Account, project: dict) -> None:
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "Backfilled", "due_date": "2020-01-01"},
        headers=member.headers,
    )
    assert response.status_code == 201


def test_a_blank_description_is_stored_as_none(
    client: TestClient, member: Account, project: dict
) -> None:
    body = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "x", "description": "   "},
        headers=member.headers,
    ).json()
    assert body["description"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "a" * (MAX_TITLE_LENGTH + 1)},
        {"title": "x", "description": "a" * (MAX_TASK_DESCRIPTION_LENGTH + 1)},
        {"title": "x", "status": "blocked"},
        {"title": "x", "status": "DONE"},
        {"title": "x", "due_date": "31/01/2030"},
        {"title": "x", "due_date": "2030-02-30"},
        {"title": "x", "assignee_id": "max"},
        {},
    ],
    ids=[
        "empty-title",
        "blank-title",
        "long-title",
        "long-description",
        "unknown-status",
        "wrong-case-status",
        "bad-date-format",
        "impossible-date",
        "non-numeric-assignee",
        "missing-title",
    ],
)
def test_invalid_task_bodies_are_rejected(
    client: TestClient, member: Account, project: dict, payload: dict
) -> None:
    response = client.post(f"/projects/{project['id']}/tasks", json=payload, headers=member.headers)
    assert response.status_code == 422


def test_a_task_cannot_be_assigned_to_a_non_member(
    client: TestClient, member: Account, outsider: Account, project: dict
) -> None:
    response = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "x", "assignee_id": outsider.id},
        headers=member.headers,
    )
    assert response.status_code == 422
    assert "member" in response.json()["detail"]


def test_a_missing_user_id_gets_the_same_error_as_a_non_member(
    client: TestClient, member: Account, outsider: Account, project: dict
) -> None:
    url = f"/projects/{project['id']}/tasks"
    real = client.post(url, json={"title": "x", "assignee_id": outsider.id}, headers=member.headers)
    fake = client.post(url, json={"title": "x", "assignee_id": 99999}, headers=member.headers)
    assert real.status_code == fake.status_code == 422
    assert real.json() == fake.json()


def test_an_admin_not_on_the_team_can_create_tasks_but_not_be_assigned(
    client: TestClient, admin: Account, project: dict
) -> None:
    url = f"/projects/{project['id']}/tasks"
    assert client.post(url, json={"title": "x"}, headers=admin.headers).status_code == 201
    response = client.post(url, json={"title": "x", "assignee_id": admin.id}, headers=admin.headers)
    assert response.status_code == 422


def test_a_non_member_cannot_create_tasks(
    client: TestClient, outsider: Account, project: dict
) -> None:
    response = client.post(
        f"/projects/{project['id']}/tasks", json={"title": "x"}, headers=outsider.headers
    )
    assert response.status_code == 404


# ----------------------------------------------------------------- list / view


def test_tasks_are_listed_soonest_due_first_with_undated_last(
    client: TestClient, member: Account, project: dict
) -> None:
    url = f"/projects/{project['id']}/tasks"
    for title, due in [("none", None), ("late", "2030-03-01"), ("soon", "2030-01-01")]:
        client.post(url, json={"title": title, "due_date": due}, headers=member.headers)

    titles = [t["title"] for t in client.get(url, headers=member.headers).json()]
    assert titles == ["soon", "late", "none"]


def test_tasks_can_be_filtered_by_status_and_assignee(
    client: TestClient, member: Account, lead: Account, project: dict
) -> None:
    url = f"/projects/{project['id']}/tasks"
    client.post(url, json={"title": "a", "status": "done"}, headers=member.headers)
    client.post(url, json={"title": "b", "assignee_id": lead.id}, headers=member.headers)
    client.post(
        url, json={"title": "c", "assignee_id": lead.id, "status": "done"}, headers=member.headers
    )

    def titles(params: dict) -> list[str]:
        return [t["title"] for t in client.get(url, params=params, headers=member.headers).json()]

    assert titles({"status": "done"}) == ["a", "c"]
    assert titles({"assignee_id": lead.id}) == ["b", "c"]
    assert titles({"status": "done", "assignee_id": lead.id}) == ["c"]
    assert client.get(url, params={"status": "nope"}, headers=member.headers).status_code == 422


def test_a_non_member_cannot_see_a_task(client: TestClient, outsider: Account, task: dict) -> None:
    hidden = client.get(f"/tasks/{task['id']}", headers=outsider.headers)
    missing = client.get("/tasks/99999", headers=outsider.headers)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_a_non_member_cannot_list_a_projects_tasks(
    client: TestClient, outsider: Account, project: dict
) -> None:
    response = client.get(f"/projects/{project['id']}/tasks", headers=outsider.headers)
    assert response.status_code == 404


# --------------------------------------------------------------------- update


def test_patch_changes_only_the_fields_sent(
    client: TestClient, member: Account, task: dict
) -> None:
    body = _patch(client, member.headers, task["id"], title="Write the homepage")
    assert body["title"] == "Write the homepage"
    assert body["assignee"]["id"] == member.id
    assert body["status"] == "todo"


def test_null_unassigns_and_clears_the_due_date(
    client: TestClient, member: Account, task: dict
) -> None:
    _patch(client, member.headers, task["id"], due_date="2030-01-01")
    body = _patch(client, member.headers, task["id"], assignee_id=None, due_date=None)
    assert body["assignee"] is None
    assert body["due_date"] is None


def test_any_member_can_reassign_to_another_member(
    client: TestClient, member: Account, lead: Account, task: dict
) -> None:
    assert _patch(client, member.headers, task["id"], assignee_id=lead.id)["assignee"]["id"] == (
        lead.id
    )


def test_reassigning_to_a_non_member_is_rejected_and_changes_nothing(
    client: TestClient, member: Account, outsider: Account, task: dict
) -> None:
    response = client.patch(
        f"/tasks/{task['id']}",
        json={"assignee_id": outsider.id, "title": "sneaky"},
        headers=member.headers,
    )
    assert response.status_code == 422
    body = client.get(f"/tasks/{task['id']}", headers=member.headers).json()
    assert body["assignee"]["id"] == member.id
    assert body["title"] == "Write homepage"


@pytest.mark.parametrize(
    "payload",
    [{"title": None}, {"status": None}, {"title": ""}, {"status": "blocked"}],
    ids=["null-title", "null-status", "empty-title", "unknown-status"],
)
def test_invalid_updates_are_rejected(
    client: TestClient, member: Account, task: dict, payload: dict
) -> None:
    response = client.patch(f"/tasks/{task['id']}", json=payload, headers=member.headers)
    assert response.status_code == 422


def test_an_empty_patch_changes_nothing(client: TestClient, member: Account, task: dict) -> None:
    body = _patch(client, member.headers, task["id"])
    assert body["title"] == task["title"]


def test_a_non_member_cannot_update_a_task(
    client: TestClient, outsider: Account, task: dict
) -> None:
    response = client.patch(f"/tasks/{task['id']}", json={"title": "x"}, headers=outsider.headers)
    assert response.status_code == 404


# ------------------------------------------------------------- completed_at


def test_completed_at_is_set_when_done_and_cleared_when_reopened(
    client: TestClient, member: Account, task: dict
) -> None:
    done = _patch(client, member.headers, task["id"], status="done")
    assert done["completed_at"] is not None

    reopened = _patch(client, member.headers, task["id"], status="in_progress")
    assert reopened["completed_at"] is None

    done_again = _patch(client, member.headers, task["id"], status="done")
    assert done_again["completed_at"] is not None


def test_saving_done_again_keeps_the_original_completion_time(
    client: TestClient, member: Account, task: dict
) -> None:
    first = _patch(client, member.headers, task["id"], status="done")["completed_at"]
    again = _patch(client, member.headers, task["id"], status="done", title="renamed")
    assert again["completed_at"] == first


def test_completed_at_is_a_recent_utc_time(client: TestClient, member: Account, task: dict) -> None:
    stamp = datetime.fromisoformat(
        _patch(client, member.headers, task["id"], status="done")["completed_at"]
    )
    now = utcnow()
    assert now - timedelta(minutes=1) <= stamp <= now + timedelta(seconds=1)


# --------------------------------------------------------------------- delete


def test_the_lead_deletes_a_task_and_its_subtasks(
    client: TestClient, lead: Account, member: Account, task: dict
) -> None:
    sub = client.post(
        f"/tasks/{task['id']}/subtasks", json={"title": "step"}, headers=member.headers
    ).json()["subtasks"][0]

    assert client.delete(f"/tasks/{task['id']}", headers=lead.headers).status_code == 204
    assert client.get(f"/tasks/{task['id']}", headers=lead.headers).status_code == 404
    assert client.delete(f"/subtasks/{sub['id']}", headers=lead.headers).status_code == 404


def test_a_plain_member_cannot_delete_a_task_even_their_own(
    client: TestClient, member: Account, task: dict
) -> None:
    assert client.delete(f"/tasks/{task['id']}", headers=member.headers).status_code == 403


def test_an_admin_can_delete_any_task(client: TestClient, admin: Account, task: dict) -> None:
    assert client.delete(f"/tasks/{task['id']}", headers=admin.headers).status_code == 204


def test_a_non_member_deleting_a_task_gets_404(
    client: TestClient, outsider: Account, task: dict
) -> None:
    assert client.delete(f"/tasks/{task['id']}", headers=outsider.headers).status_code == 404


# ------------------------------------------------------------------- subtasks


def test_subtasks_are_added_and_progress_is_reported(
    client: TestClient, member: Account, lead: Account, task: dict
) -> None:
    url = f"/tasks/{task['id']}/subtasks"
    client.post(url, json={"title": "draft"}, headers=member.headers)
    body = client.post(
        url,
        json={"title": "review", "assignee_id": lead.id, "due_date": "2030-01-01"},
        headers=member.headers,
    ).json()

    assert [s["title"] for s in body["subtasks"]] == ["draft", "review"]
    assert body["subtasks"][1]["assignee"]["id"] == lead.id
    assert (body["subtasks_done"], body["subtasks_total"]) == (0, 2)

    first = body["subtasks"][0]["id"]
    body = client.patch(
        f"/subtasks/{first}", json={"status": "done"}, headers=member.headers
    ).json()
    assert (body["subtasks_done"], body["subtasks_total"]) == (1, 2)


def test_subtask_progress_shows_in_the_task_list(
    client: TestClient, member: Account, project: dict, task: dict
) -> None:
    client.post(
        f"/tasks/{task['id']}/subtasks",
        json={"title": "s", "status": "done"},
        headers=member.headers,
    )
    [listed] = client.get(f"/projects/{project['id']}/tasks", headers=member.headers).json()
    assert (listed["subtasks_done"], listed["subtasks_total"]) == (1, 1)
    assert "subtasks" not in listed


def test_a_subtask_cannot_be_assigned_to_a_non_member(
    client: TestClient, member: Account, outsider: Account, task: dict
) -> None:
    url = f"/tasks/{task['id']}/subtasks"
    response = client.post(
        url, json={"title": "s", "assignee_id": outsider.id}, headers=member.headers
    )
    assert response.status_code == 422

    sub_id = client.post(url, json={"title": "s"}, headers=member.headers).json()["subtasks"][0][
        "id"
    ]
    response = client.patch(
        f"/subtasks/{sub_id}", json={"assignee_id": outsider.id}, headers=member.headers
    )
    assert response.status_code == 422


def test_subtask_null_and_invalid_updates(client: TestClient, member: Account, task: dict) -> None:
    sub_id = client.post(
        f"/tasks/{task['id']}/subtasks",
        json={"title": "s", "assignee_id": member.id, "due_date": "2030-01-01"},
        headers=member.headers,
    ).json()["subtasks"][0]["id"]
    url = f"/subtasks/{sub_id}"

    cleared = client.patch(
        url, json={"assignee_id": None, "due_date": None}, headers=member.headers
    ).json()["subtasks"][0]
    assert cleared["assignee"] is None and cleared["due_date"] is None

    assert client.patch(url, json={"title": None}, headers=member.headers).status_code == 422
    assert client.patch(url, json={"status": "nope"}, headers=member.headers).status_code == 422


def test_only_the_lead_or_an_admin_deletes_subtasks(
    client: TestClient, lead: Account, member: Account, outsider: Account, task: dict
) -> None:
    sub_id = client.post(
        f"/tasks/{task['id']}/subtasks", json={"title": "s"}, headers=member.headers
    ).json()["subtasks"][0]["id"]
    url = f"/subtasks/{sub_id}"

    assert client.delete(url, headers=outsider.headers).status_code == 404
    assert client.delete(url, headers=member.headers).status_code == 403
    assert client.delete(url, headers=lead.headers).status_code == 204
    assert client.get(f"/tasks/{task['id']}", headers=lead.headers).json()["subtasks"] == []


def test_a_non_member_cannot_touch_subtasks(
    client: TestClient, member: Account, outsider: Account, task: dict
) -> None:
    sub_id = client.post(
        f"/tasks/{task['id']}/subtasks", json={"title": "s"}, headers=member.headers
    ).json()["subtasks"][0]["id"]

    assert (
        client.post(
            f"/tasks/{task['id']}/subtasks", json={"title": "x"}, headers=outsider.headers
        ).status_code
        == 404
    )
    assert (
        client.patch(
            f"/subtasks/{sub_id}", json={"title": "x"}, headers=outsider.headers
        ).status_code
        == 404
    )
    assert client.patch(
        "/subtasks/99999", json={"title": "x"}, headers=member.headers
    ).status_code == (404)


# ------------------------------------------------- leaving a team unassigns


def test_leaving_a_team_unassigns_tasks_and_subtasks_there_only(
    client: TestClient,
    lead: Account,
    member: Account,
    make_account: Callable[..., Account],
    team: dict,
    project: dict,
    task: dict,
) -> None:
    # Max also belongs to a second team, Beta, with work assigned to him there.
    beta_lead = make_account("Bea", "project_lead")
    beta = client.post("/teams", json={"name": "Beta"}, headers=beta_lead.headers).json()
    client.post(
        f"/teams/{beta['id']}/members", json={"email": member.email}, headers=beta_lead.headers
    )
    beta_project = client.post(
        f"/teams/{beta['id']}/projects", json={"name": "B"}, headers=beta_lead.headers
    ).json()
    beta_task = client.post(
        f"/projects/{beta_project['id']}/tasks",
        json={"title": "beta work", "assignee_id": member.id},
        headers=beta_lead.headers,
    ).json()

    # In Alpha, Max has the task fixture plus an assigned subtask.
    sub_id = client.post(
        f"/tasks/{task['id']}/subtasks",
        json={"title": "s", "assignee_id": member.id},
        headers=member.headers,
    ).json()["subtasks"][0]["id"]

    # Max leaves Alpha.
    response = client.delete(f"/teams/{team['id']}/members/{member.id}", headers=member.headers)
    assert response.status_code == 204

    alpha_task = client.get(f"/tasks/{task['id']}", headers=lead.headers).json()
    assert alpha_task["assignee"] is None
    assert next(s for s in alpha_task["subtasks"] if s["id"] == sub_id)["assignee"] is None

    # His Beta work is untouched.
    beta_after = client.get(f"/tasks/{beta_task['id']}", headers=beta_lead.headers).json()
    assert beta_after["assignee"]["id"] == member.id


def test_being_removed_by_the_lead_also_unassigns(
    client: TestClient, lead: Account, member: Account, team: dict, task: dict
) -> None:
    client.delete(f"/teams/{team['id']}/members/{member.id}", headers=lead.headers)
    assert client.get(f"/tasks/{task['id']}", headers=lead.headers).json()["assignee"] is None


def test_other_peoples_assignments_survive_someone_leaving(
    client: TestClient, lead: Account, member: Account, team: dict, project: dict
) -> None:
    leads_task = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "lena's", "assignee_id": lead.id},
        headers=lead.headers,
    ).json()
    client.delete(f"/teams/{team['id']}/members/{member.id}", headers=member.headers)
    body = client.get(f"/tasks/{leads_task['id']}", headers=lead.headers).json()
    assert body["assignee"]["id"] == lead.id


# ---------------------------------------------------------------------- login


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("post", "/projects/1/tasks"),
        ("get", "/projects/1/tasks"),
        ("get", "/tasks/1"),
        ("patch", "/tasks/1"),
        ("delete", "/tasks/1"),
        ("post", "/tasks/1/subtasks"),
        ("patch", "/subtasks/1"),
        ("delete", "/subtasks/1"),
    ],
)
def test_every_task_route_requires_login(client: TestClient, method: str, url: str) -> None:
    assert client.request(method.upper(), url, json={"title": "x"}).status_code == 401


def test_due_dates_round_trip_as_plain_dates(
    client: TestClient, member: Account, project: dict
) -> None:
    today = local_today().isoformat()
    body = client.post(
        f"/projects/{project['id']}/tasks",
        json={"title": "x", "due_date": today},
        headers=member.headers,
    ).json()
    assert body["due_date"] == today
