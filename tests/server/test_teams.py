"""Tests for team management (context.md goal #1).

The rules under test, from ``server.services.team_service``:

* admins and project leads create teams; the creator becomes lead + member;
* a team's lead and any admin manage it; nobody else does;
* any member may leave, except the lead, who must hand the lead over first;
* non-members (other than admins) get 404, as if the team did not exist.
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from server.models.project import Project
from server.models.team import Team, team_members
from server.schemas.team import MAX_TEAM_NAME_LENGTH
from shared.roles import ROLE_MEMBER, ROLE_PROJECT_LEAD
from tests.server.conftest import Account, set_role


def _member_ids(body: dict) -> list[int]:
    return [m["id"] for m in body["members"]]


# --------------------------------------------------------------------- create


def test_a_project_lead_creates_a_team_and_becomes_its_lead_and_member(
    client: TestClient, lead: Account
) -> None:
    response = client.post("/teams", json={"name": "Alpha"}, headers=lead.headers)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["name"] == "Alpha"
    assert body["lead"]["id"] == lead.id
    assert _member_ids(body) == [lead.id]
    assert body["created_at"]


def test_an_admin_can_create_a_team(client: TestClient, admin: Account) -> None:
    response = client.post("/teams", json={"name": "Alpha"}, headers=admin.headers)
    assert response.status_code == 201
    assert response.json()["lead"]["id"] == admin.id


def test_a_plain_member_cannot_create_a_team(client: TestClient, member: Account) -> None:
    response = client.post("/teams", json={"name": "Alpha"}, headers=member.headers)
    assert response.status_code == 403
    assert client.get("/teams", headers=member.headers).json() == []


def test_the_team_name_is_trimmed(client: TestClient, lead: Account) -> None:
    response = client.post("/teams", json={"name": "  Alpha  "}, headers=lead.headers)
    assert response.json()["name"] == "Alpha"


@pytest.mark.parametrize(
    "payload",
    [{"name": ""}, {"name": "   "}, {"name": "a" * (MAX_TEAM_NAME_LENGTH + 1)}, {}],
    ids=["empty", "blank", "too-long", "missing"],
)
def test_an_invalid_name_is_rejected(client: TestClient, lead: Account, payload: dict) -> None:
    assert client.post("/teams", json=payload, headers=lead.headers).status_code == 422


def test_a_name_at_the_length_limit_is_accepted(client: TestClient, lead: Account) -> None:
    name = "a" * MAX_TEAM_NAME_LENGTH
    assert client.post("/teams", json={"name": name}, headers=lead.headers).status_code == 201


@pytest.mark.parametrize("duplicate", ["Alpha", "alpha", "ALPHA", "  Alpha "])
def test_a_duplicate_name_is_rejected_ignoring_case(
    client: TestClient, lead: Account, admin: Account, duplicate: str
) -> None:
    client.post("/teams", json={"name": "Alpha"}, headers=lead.headers)

    # A different creator, to show uniqueness is global, not per-user.
    response = client.post("/teams", json={"name": duplicate}, headers=admin.headers)
    assert response.status_code == 409


def test_the_database_itself_enforces_case_insensitive_names(
    session_factory: sessionmaker[Session], lead: Account
) -> None:
    """The service checks first, but the index is what holds if two requests race."""
    db = session_factory()
    try:
        db.add(Team(name="Alpha", lead_id=lead.id))
        db.commit()
        db.add(Team(name="ALPHA", lead_id=lead.id))
        with pytest.raises(IntegrityError):
            db.commit()
    finally:
        db.rollback()
        db.close()


def test_a_demoted_lead_cannot_create_teams_but_still_manages_their_own(
    client: TestClient,
    lead: Account,
    outsider: Account,
    team: dict,
    session_factory: sessionmaker[Session],
) -> None:
    set_role(session_factory, lead.email, ROLE_MEMBER)

    assert client.post("/teams", json={"name": "Beta"}, headers=lead.headers).status_code == 403
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=lead.headers
    )
    assert response.status_code == 201


# ----------------------------------------------------------------------- list


def test_list_shows_only_my_teams(
    client: TestClient, lead: Account, admin: Account, member: Account, team: dict
) -> None:
    client.post("/teams", json={"name": "Admins Only"}, headers=admin.headers)

    names = [t["name"] for t in client.get("/teams", headers=member.headers).json()]
    assert names == ["Alpha"]


def test_an_admin_lists_every_team(
    client: TestClient, admin: Account, lead: Account, team: dict
) -> None:
    client.post("/teams", json={"name": "beta"}, headers=admin.headers)
    client.post("/teams", json={"name": "Gamma"}, headers=lead.headers)

    names = [t["name"] for t in client.get("/teams", headers=admin.headers).json()]
    assert names == ["Alpha", "beta", "Gamma"]  # sorted ignoring case


def test_list_reports_the_lead_and_member_count(
    client: TestClient, member: Account, lead: Account, team: dict
) -> None:
    [summary] = client.get("/teams", headers=member.headers).json()
    assert summary["lead"]["id"] == lead.id
    assert summary["member_count"] == 2
    assert "members" not in summary


def test_a_user_with_no_teams_gets_an_empty_list(client: TestClient, outsider: Account) -> None:
    assert client.get("/teams", headers=outsider.headers).json() == []


# ----------------------------------------------------------------------- view


def test_a_member_can_view_the_team(client: TestClient, member: Account, team: dict) -> None:
    response = client.get(f"/teams/{team['id']}", headers=member.headers)
    assert response.status_code == 200
    assert member.id in _member_ids(response.json())


def test_members_never_expose_password_hashes(
    client: TestClient, member: Account, team: dict
) -> None:
    assert "password" not in client.get(f"/teams/{team['id']}", headers=member.headers).text


def test_an_admin_can_view_a_team_they_are_not_on(
    client: TestClient, admin: Account, team: dict
) -> None:
    assert client.get(f"/teams/{team['id']}", headers=admin.headers).status_code == 200


def test_a_non_member_sees_the_same_404_as_for_a_missing_team(
    client: TestClient, outsider: Account, team: dict
) -> None:
    hidden = client.get(f"/teams/{team['id']}", headers=outsider.headers)
    missing = client.get("/teams/99999", headers=outsider.headers)

    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


def test_a_non_numeric_team_id_is_rejected(client: TestClient, member: Account) -> None:
    assert client.get("/teams/abc", headers=member.headers).status_code == 422


# --------------------------------------------------------------------- rename


def test_the_lead_can_rename_the_team(client: TestClient, lead: Account, team: dict) -> None:
    response = client.patch(f"/teams/{team['id']}", json={"name": "Omega"}, headers=lead.headers)
    assert response.status_code == 200
    assert response.json()["name"] == "Omega"


def test_an_admin_can_rename_any_team(client: TestClient, admin: Account, team: dict) -> None:
    response = client.patch(f"/teams/{team['id']}", json={"name": "Omega"}, headers=admin.headers)
    assert response.status_code == 200


def test_a_plain_member_cannot_rename(client: TestClient, member: Account, team: dict) -> None:
    response = client.patch(f"/teams/{team['id']}", json={"name": "Omega"}, headers=member.headers)
    assert response.status_code == 403


def test_a_project_lead_on_the_team_who_is_not_its_lead_cannot_rename(
    client: TestClient,
    make_account: Callable[..., Account],
    lead: Account,
    team: dict,
) -> None:
    other_lead = make_account("Pat", ROLE_PROJECT_LEAD)
    client.post(
        f"/teams/{team['id']}/members", json={"email": other_lead.email}, headers=lead.headers
    )

    response = client.patch(
        f"/teams/{team['id']}", json={"name": "Mine Now"}, headers=other_lead.headers
    )
    assert response.status_code == 403


def test_a_project_lead_not_on_the_team_gets_404(
    client: TestClient, make_account: Callable[..., Account], team: dict
) -> None:
    other_lead = make_account("Pat", ROLE_PROJECT_LEAD)
    response = client.patch(
        f"/teams/{team['id']}", json={"name": "Mine Now"}, headers=other_lead.headers
    )
    assert response.status_code == 404


def test_renaming_to_another_teams_name_is_rejected(
    client: TestClient, lead: Account, team: dict
) -> None:
    client.post("/teams", json={"name": "Beta"}, headers=lead.headers)
    response = client.patch(f"/teams/{team['id']}", json={"name": "BETA"}, headers=lead.headers)
    assert response.status_code == 409


def test_a_team_can_change_the_case_of_its_own_name(
    client: TestClient, lead: Account, team: dict
) -> None:
    response = client.patch(f"/teams/{team['id']}", json={"name": "ALPHA"}, headers=lead.headers)
    assert response.status_code == 200
    assert response.json()["name"] == "ALPHA"


def test_renaming_to_a_blank_name_is_rejected(
    client: TestClient, lead: Account, team: dict
) -> None:
    response = client.patch(f"/teams/{team['id']}", json={"name": "  "}, headers=lead.headers)
    assert response.status_code == 422


# --------------------------------------------------------------------- delete


def test_the_lead_can_delete_the_team_and_its_memberships_go_too(
    client: TestClient,
    lead: Account,
    team: dict,
    session_factory: sessionmaker[Session],
) -> None:
    assert client.delete(f"/teams/{team['id']}", headers=lead.headers).status_code == 204
    assert client.get(f"/teams/{team['id']}", headers=lead.headers).status_code == 404

    db = session_factory()
    try:
        rows = db.execute(select(team_members).where(team_members.c.team_id == team["id"]))
        assert rows.all() == []
    finally:
        db.close()


def test_an_admin_can_delete_any_team(client: TestClient, admin: Account, team: dict) -> None:
    assert client.delete(f"/teams/{team['id']}", headers=admin.headers).status_code == 204


def test_a_plain_member_cannot_delete(client: TestClient, member: Account, team: dict) -> None:
    assert client.delete(f"/teams/{team['id']}", headers=member.headers).status_code == 403
    assert client.get(f"/teams/{team['id']}", headers=member.headers).status_code == 200


def test_a_non_member_cannot_delete(client: TestClient, outsider: Account, team: dict) -> None:
    assert client.delete(f"/teams/{team['id']}", headers=outsider.headers).status_code == 404


def test_a_team_with_projects_cannot_be_deleted(
    client: TestClient,
    lead: Account,
    team: dict,
    session_factory: sessionmaker[Session],
) -> None:
    db = session_factory()
    try:
        db.add(Project(team_id=team["id"], name="Website", status="active"))
        db.commit()
    finally:
        db.close()

    assert client.delete(f"/teams/{team['id']}", headers=lead.headers).status_code == 409
    assert client.get(f"/teams/{team['id']}", headers=lead.headers).status_code == 200


def test_deleting_a_missing_team_is_404(client: TestClient, admin: Account) -> None:
    assert client.delete("/teams/99999", headers=admin.headers).status_code == 404


# ----------------------------------------------------------------- add member


def test_the_lead_adds_a_member_who_can_then_see_the_team(
    client: TestClient, lead: Account, outsider: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=lead.headers
    )
    assert response.status_code == 201
    assert outsider.id in _member_ids(response.json())

    assert client.get(f"/teams/{team['id']}", headers=outsider.headers).status_code == 200
    assert [t["id"] for t in client.get("/teams", headers=outsider.headers).json()] == [team["id"]]


def test_an_admin_can_add_members_to_any_team(
    client: TestClient, admin: Account, outsider: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=admin.headers
    )
    assert response.status_code == 201


def test_adding_by_email_ignores_case_and_spaces(
    client: TestClient, lead: Account, outsider: Account, team: dict
) -> None:
    email = f"  {outsider.email.upper()} "
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": email}, headers=lead.headers
    )
    assert response.status_code == 201
    assert outsider.id in _member_ids(response.json())


def test_adding_an_unknown_email_is_404(client: TestClient, lead: Account, team: dict) -> None:
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": "ghost@example.com"}, headers=lead.headers
    )
    assert response.status_code == 404


def test_adding_an_existing_member_is_409(
    client: TestClient, lead: Account, member: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": member.email}, headers=lead.headers
    )
    assert response.status_code == 409
    assert (
        _member_ids(client.get(f"/teams/{team['id']}", headers=lead.headers).json()).count(
            member.id
        )
        == 1
    )


def test_a_plain_member_cannot_add_members(
    client: TestClient, member: Account, outsider: Account, team: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=member.headers
    )
    assert response.status_code == 403


def test_a_non_manager_cannot_use_add_member_to_probe_emails(
    client: TestClient, member: Account, outsider: Account, team: dict
) -> None:
    """Real and fake emails must get the same answer from someone who cannot add anyone."""
    url = f"/teams/{team['id']}/members"
    real = client.post(url, json={"email": outsider.email}, headers=member.headers)
    fake = client.post(url, json={"email": "ghost@example.com"}, headers=member.headers)
    assert real.status_code == fake.status_code == 403


def test_a_non_member_cannot_add_members(client: TestClient, outsider: Account, team: dict) -> None:
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=outsider.headers
    )
    assert response.status_code == 404


def test_adding_with_an_empty_email_is_422(client: TestClient, lead: Account, team: dict) -> None:
    response = client.post(f"/teams/{team['id']}/members", json={"email": ""}, headers=lead.headers)
    assert response.status_code == 422


# -------------------------------------------------------------- remove member


def test_the_lead_removes_a_member_who_then_loses_access(
    client: TestClient, lead: Account, member: Account, team: dict
) -> None:
    url = f"/teams/{team['id']}/members/{member.id}"
    assert client.delete(url, headers=lead.headers).status_code == 204

    assert client.get(f"/teams/{team['id']}", headers=member.headers).status_code == 404
    assert client.get("/teams", headers=member.headers).json() == []


def test_a_member_can_leave(client: TestClient, member: Account, team: dict) -> None:
    url = f"/teams/{team['id']}/members/{member.id}"
    assert client.delete(url, headers=member.headers).status_code == 204
    assert client.get(f"/teams/{team['id']}", headers=member.headers).status_code == 404


def test_a_member_cannot_remove_someone_else(
    client: TestClient, lead: Account, member: Account, team: dict
) -> None:
    url = f"/teams/{team['id']}/members/{lead.id}"
    assert client.delete(url, headers=member.headers).status_code == 403


def test_the_lead_cannot_be_removed_even_by_an_admin(
    client: TestClient, admin: Account, lead: Account, team: dict
) -> None:
    url = f"/teams/{team['id']}/members/{lead.id}"
    assert client.delete(url, headers=admin.headers).status_code == 409
    assert client.delete(url, headers=lead.headers).status_code == 409


def test_removing_someone_not_on_the_team_is_404(
    client: TestClient, lead: Account, outsider: Account, team: dict
) -> None:
    assert (
        client.delete(
            f"/teams/{team['id']}/members/{outsider.id}", headers=lead.headers
        ).status_code
        == 404
    )
    assert (
        client.delete(f"/teams/{team['id']}/members/99999", headers=lead.headers).status_code == 404
    )


def test_a_non_member_cannot_remove_anyone(
    client: TestClient, outsider: Account, member: Account, team: dict
) -> None:
    url = f"/teams/{team['id']}/members/{member.id}"
    assert client.delete(url, headers=outsider.headers).status_code == 404


# ---------------------------------------------------------------- change lead


def test_handing_over_the_lead_moves_management_rights(
    client: TestClient, lead: Account, member: Account, outsider: Account, team: dict
) -> None:
    response = client.put(
        f"/teams/{team['id']}/lead", json={"user_id": member.id}, headers=lead.headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["lead"]["id"] == member.id
    assert lead.id in _member_ids(body)  # the old lead stays on the team

    # The new lead can manage...
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=member.headers
    )
    assert response.status_code == 201
    # ...and the old lead immediately cannot.
    response = client.patch(f"/teams/{team['id']}", json={"name": "Nope"}, headers=lead.headers)
    assert response.status_code == 403


def test_after_handing_over_the_old_lead_can_leave(
    client: TestClient, lead: Account, member: Account, team: dict
) -> None:
    client.put(f"/teams/{team['id']}/lead", json={"user_id": member.id}, headers=lead.headers)
    url = f"/teams/{team['id']}/members/{lead.id}"
    assert client.delete(url, headers=lead.headers).status_code == 204


def test_the_lead_cannot_go_to_a_non_member(
    client: TestClient, lead: Account, outsider: Account, team: dict
) -> None:
    response = client.put(
        f"/teams/{team['id']}/lead", json={"user_id": outsider.id}, headers=lead.headers
    )
    assert response.status_code == 409
    assert client.get(f"/teams/{team['id']}", headers=lead.headers).json()["lead"]["id"] == lead.id


def test_a_plain_member_cannot_take_the_lead(
    client: TestClient, member: Account, team: dict
) -> None:
    response = client.put(
        f"/teams/{team['id']}/lead", json={"user_id": member.id}, headers=member.headers
    )
    assert response.status_code == 403


def test_an_admin_can_reassign_the_lead(
    client: TestClient, admin: Account, member: Account, team: dict
) -> None:
    response = client.put(
        f"/teams/{team['id']}/lead", json={"user_id": member.id}, headers=admin.headers
    )
    assert response.status_code == 200
    assert response.json()["lead"]["id"] == member.id


def test_making_the_current_lead_lead_again_changes_nothing(
    client: TestClient, lead: Account, team: dict
) -> None:
    response = client.put(
        f"/teams/{team['id']}/lead", json={"user_id": lead.id}, headers=lead.headers
    )
    assert response.status_code == 200
    assert response.json()["lead"]["id"] == lead.id


# ---------------------------------------------------------------------- login


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/teams", {"name": "Alpha"}),
        ("get", "/teams", None),
        ("get", "/teams/1", None),
        ("patch", "/teams/1", {"name": "Omega"}),
        ("delete", "/teams/1", None),
        ("post", "/teams/1/members", {"email": "a@example.com"}),
        ("delete", "/teams/1/members/1", None),
        ("put", "/teams/1/lead", {"user_id": 1}),
    ],
)
def test_every_team_route_requires_login(
    client: TestClient, method: str, url: str, body: dict | None
) -> None:
    kwargs = {"json": body} if body is not None else {}
    assert client.request(method.upper(), url, **kwargs).status_code == 401


def test_the_name_index_exists_in_the_model_schema(
    session_factory: sessionmaker[Session],
) -> None:
    """The migrated schema is checked in test_startup.py."""
    db = session_factory()
    try:
        names = {
            row[0]
            for row in db.execute(
                text("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='teams'")
            )
        }
    finally:
        db.close()
    assert "uq_teams_name_lower" in names
