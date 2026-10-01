"""Tests for projects (context.md goals #5-6).

Uses the shared fixtures from conftest.py: Lena (``lead``) leads team Alpha,
Max (``member``) is on it, Ada (``admin``) and Olga (``outsider``) are not.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from server.models.subtask import Subtask
from server.models.task import Task
from server.schemas.project import MAX_PROJECT_DESCRIPTION_LENGTH, MAX_PROJECT_NAME_LENGTH
from tests.server.conftest import Account


@pytest.fixture
def project(client: TestClient, lead: Account, team: dict) -> dict:
    response = client.post(
        f"/teams/{team['id']}/projects",
        json={"name": "Website", "description": "The public site"},
        headers=lead.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _add_task(client: TestClient, headers: dict, project_id: int, **fields) -> dict:
    response = client.post(
        f"/projects/{project_id}/tasks", json={"title": "Task", **fields}, headers=headers
    )
    assert response.status_code == 201, response.text
    return response.json()


# --------------------------------------------------------------------- create


def test_the_lead_creates_an_active_project_with_no_tasks(
    client: TestClient, lead: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "  Website  "}, headers=lead.headers
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Website"
    assert body["team_id"] == team["id"]
    assert body["status"] == "active"
    assert body["description"] is None
    assert body["tasks"] == {"todo": 0, "in_progress": 0, "done": 0, "total": 0}


def test_an_admin_can_create_a_project_in_any_team(
    client: TestClient, admin: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Website"}, headers=admin.headers
    )
    assert response.status_code == 201


def test_a_plain_member_cannot_create_a_project(
    client: TestClient, member: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Website"}, headers=member.headers
    )
    assert response.status_code == 403


def test_a_non_member_cannot_create_a_project(
    client: TestClient, outsider: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Website"}, headers=outsider.headers
    )
    assert response.status_code == 404


def test_creating_in_a_missing_team_is_404(client: TestClient, admin: Account) -> None:
    response = client.post("/teams/99999/projects", json={"name": "X"}, headers=admin.headers)
    assert response.status_code == 404


@pytest.mark.parametrize(
    "payload",
    [
        {"name": ""},
        {"name": "   "},
        {"name": "a" * (MAX_PROJECT_NAME_LENGTH + 1)},
        {"name": "ok", "description": "a" * (MAX_PROJECT_DESCRIPTION_LENGTH + 1)},
        {},
    ],
    ids=["empty", "blank", "long-name", "long-description", "missing"],
)
def test_invalid_project_bodies_are_rejected(
    client: TestClient, lead: Account, team: dict, payload: dict
) -> None:
    response = client.post(f"/teams/{team['id']}/projects", json=payload, headers=lead.headers)
    assert response.status_code == 422


def test_a_new_project_cannot_be_created_already_completed(
    client: TestClient, lead: Account, team: dict
) -> None:
    """``status`` is not a create field; extra fields are ignored, not obeyed."""
    response = client.post(
        f"/teams/{team['id']}/projects",
        json={"name": "Website", "status": "completed"},
        headers=lead.headers,
    )
    assert response.json()["status"] == "active"


# ----------------------------------------------------------------- list / view


def test_members_list_projects_active_first_then_by_name(
    client: TestClient, lead: Account, member: Account, team: dict
) -> None:
    url = f"/teams/{team['id']}/projects"
    for name in ("beta", "Alpha", "Gamma"):
        client.post(url, json={"name": name}, headers=lead.headers)
    gamma = next(p for p in client.get(url, headers=lead.headers).json() if p["name"] == "Gamma")
    client.patch(f"/projects/{gamma['id']}", json={"status": "completed"}, headers=lead.headers)

    names = [p["name"] for p in client.get(url, headers=member.headers).json()]
    assert names == ["Alpha", "beta", "Gamma"]


def test_a_non_member_cannot_list_or_view_projects(
    client: TestClient, outsider: Account, team: dict, project: dict
) -> None:
    listed = client.get(f"/teams/{team['id']}/projects", headers=outsider.headers)
    viewed = client.get(f"/projects/{project['id']}", headers=outsider.headers)
    missing = client.get("/projects/99999", headers=outsider.headers)

    assert listed.status_code == 404
    assert viewed.status_code == missing.status_code == 404
    assert viewed.json() == missing.json()


def test_project_task_counts_follow_the_tasks(
    client: TestClient, member: Account, project: dict
) -> None:
    for status in ("todo", "todo", "in_progress", "done"):
        _add_task(client, member.headers, project["id"], status=status)

    counts = client.get(f"/projects/{project['id']}", headers=member.headers).json()["tasks"]
    assert counts == {"todo": 2, "in_progress": 1, "done": 1, "total": 4}


# --------------------------------------------------------------------- update


def test_the_lead_can_rename_describe_and_complete_a_project(
    client: TestClient, lead: Account, project: dict
) -> None:
    response = client.patch(
        f"/projects/{project['id']}",
        json={"name": "New Site", "description": "v2", "status": "completed"},
        headers=lead.headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["description"], body["status"]) == ("New Site", "v2", "completed")


def test_a_completed_project_can_be_reopened(
    client: TestClient, lead: Account, project: dict
) -> None:
    url = f"/projects/{project['id']}"
    client.patch(url, json={"status": "completed"}, headers=lead.headers)
    assert client.patch(url, json={"status": "active"}, headers=lead.headers).json()["status"] == (
        "active"
    )


def test_patch_changes_only_the_fields_sent(
    client: TestClient, lead: Account, project: dict
) -> None:
    body = client.patch(
        f"/projects/{project['id']}", json={"name": "Renamed"}, headers=lead.headers
    ).json()
    assert body["description"] == "The public site"
    assert body["status"] == "active"


def test_the_description_can_be_cleared_with_null(
    client: TestClient, lead: Account, project: dict
) -> None:
    body = client.patch(
        f"/projects/{project['id']}", json={"description": None}, headers=lead.headers
    ).json()
    assert body["description"] is None


@pytest.mark.parametrize(
    "payload",
    [{"name": None}, {"status": None}, {"status": "archived"}, {"name": "  "}],
    ids=["null-name", "null-status", "unknown-status", "blank-name"],
)
def test_invalid_updates_are_rejected(
    client: TestClient, lead: Account, project: dict, payload: dict
) -> None:
    assert client.patch(
        f"/projects/{project['id']}", json=payload, headers=lead.headers
    ).status_code == (422)


def test_a_plain_member_cannot_update_a_project(
    client: TestClient, member: Account, project: dict
) -> None:
    response = client.patch(
        f"/projects/{project['id']}", json={"name": "Mine"}, headers=member.headers
    )
    assert response.status_code == 403


# --------------------------------------------------------------------- delete


def test_deleting_a_project_deletes_its_tasks_and_subtasks_only(
    client: TestClient,
    lead: Account,
    team: dict,
    project: dict,
    session_factory: sessionmaker[Session],
) -> None:
    doomed = _add_task(client, lead.headers, project["id"])
    client.post(f"/tasks/{doomed['id']}/subtasks", json={"title": "step"}, headers=lead.headers)

    other = client.post(
        f"/teams/{team['id']}/projects", json={"name": "Other"}, headers=lead.headers
    ).json()
    kept = _add_task(client, lead.headers, other["id"])
    client.post(f"/tasks/{kept['id']}/subtasks", json={"title": "step"}, headers=lead.headers)

    assert client.delete(f"/projects/{project['id']}", headers=lead.headers).status_code == 204
    assert client.get(f"/projects/{project['id']}", headers=lead.headers).status_code == 404
    assert client.get(f"/tasks/{doomed['id']}", headers=lead.headers).status_code == 404

    db = session_factory()
    try:
        assert db.scalar(select(func.count()).select_from(Task)) == 1
        assert db.scalar(select(func.count()).select_from(Subtask)) == 1
    finally:
        db.close()
    assert client.get(f"/tasks/{kept['id']}", headers=lead.headers).json()["subtasks_total"] == 1


def test_a_plain_member_cannot_delete_a_project(
    client: TestClient, member: Account, project: dict
) -> None:
    assert client.delete(f"/projects/{project['id']}", headers=member.headers).status_code == 403


def test_an_admin_can_delete_any_project(client: TestClient, admin: Account, project: dict) -> None:
    assert client.delete(f"/projects/{project['id']}", headers=admin.headers).status_code == 204


def test_a_team_with_a_project_still_cannot_be_deleted(
    client: TestClient, lead: Account, team: dict, project: dict
) -> None:
    assert client.delete(f"/teams/{team['id']}", headers=lead.headers).status_code == 409


def test_after_its_last_project_is_deleted_the_team_can_be(
    client: TestClient, lead: Account, team: dict, project: dict
) -> None:
    client.delete(f"/projects/{project['id']}", headers=lead.headers)
    assert client.delete(f"/teams/{team['id']}", headers=lead.headers).status_code == 204


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("post", "/teams/1/projects"),
        ("get", "/teams/1/projects"),
        ("get", "/projects/1"),
        ("patch", "/projects/1"),
        ("delete", "/projects/1"),
    ],
)
def test_every_project_route_requires_login(client: TestClient, method: str, url: str) -> None:
    assert client.request(method.upper(), url, json={"name": "x"}).status_code == 401
