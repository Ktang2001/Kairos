"""Tests for the admin user-management routes (context.md goal #2).

Uses the shared fixtures from conftest.py: Ada (``admin``), Lena (``lead``,
a project lead), Max (``member``) and Olga (``outsider``, also a member).
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from shared.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_PROJECT_LEAD
from tests.server.conftest import Account


def _set(client: TestClient, actor: Account, user_id: int, role: str):
    return client.put(f"/users/{user_id}/role", json={"role": role}, headers=actor.headers)


# --------------------------------------------------------------------- list


def test_an_admin_lists_every_user_sorted_by_name(
    client: TestClient, admin: Account, lead: Account, member: Account, outsider: Account
) -> None:
    response = client.get("/users", headers=admin.headers)
    assert response.status_code == 200
    users = response.json()
    assert [u["name"] for u in users] == ["Ada", "Lena", "Max", "Olga"]
    assert {u["name"]: u["role"] for u in users} == {
        "Ada": ROLE_ADMIN,
        "Lena": ROLE_PROJECT_LEAD,
        "Max": ROLE_MEMBER,
        "Olga": ROLE_MEMBER,
    }


def test_the_list_never_includes_password_hashes(client: TestClient, admin: Account) -> None:
    text = client.get("/users", headers=admin.headers).text
    assert "password" not in text and "$" not in text  # PBKDF2 hashes are "salt$digest"


@pytest.mark.parametrize("who", ["lead", "member"])
def test_non_admins_cannot_list_users(
    client: TestClient, request: pytest.FixtureRequest, who: str
) -> None:
    account: Account = request.getfixturevalue(who)
    assert client.get("/users", headers=account.headers).status_code == 403


def test_listing_requires_login(client: TestClient) -> None:
    assert client.get("/users").status_code == 401


# ------------------------------------------------------------- change role


def test_an_admin_promotes_a_member_to_project_lead(
    client: TestClient, admin: Account, member: Account
) -> None:
    response = _set(client, admin, member.id, ROLE_PROJECT_LEAD)
    assert response.status_code == 200
    assert response.json() == {
        "id": member.id,
        "name": "Max",
        "email": member.email,
        "role": ROLE_PROJECT_LEAD,
    }


def test_the_new_role_takes_effect_on_the_next_request(
    client: TestClient, admin: Account, member: Account
) -> None:
    assert client.post("/teams", json={"name": "Before"}, headers=member.headers).status_code == 403
    _set(client, admin, member.id, ROLE_PROJECT_LEAD)
    assert client.post("/teams", json={"name": "After"}, headers=member.headers).status_code == 201
    assert client.get("/people/me", headers=member.headers).json()["role"] == ROLE_PROJECT_LEAD


def test_demotion_also_takes_effect_immediately(
    client: TestClient, admin: Account, lead: Account
) -> None:
    _set(client, admin, lead.id, ROLE_MEMBER)
    assert client.post("/teams", json={"name": "Nope"}, headers=lead.headers).status_code == 403


def test_an_admin_can_make_another_admin_who_can_then_manage_roles(
    client: TestClient, admin: Account, lead: Account, member: Account
) -> None:
    _set(client, admin, lead.id, ROLE_ADMIN)
    assert _set(client, lead, member.id, ROLE_PROJECT_LEAD).status_code == 200


def test_setting_the_same_role_again_is_harmless(
    client: TestClient, admin: Account, member: Account
) -> None:
    assert _set(client, admin, member.id, ROLE_MEMBER).json()["role"] == ROLE_MEMBER


@pytest.mark.parametrize("role", [ROLE_MEMBER, ROLE_PROJECT_LEAD, ROLE_ADMIN])
def test_an_admin_cannot_change_their_own_role(
    client: TestClient, admin: Account, role: str
) -> None:
    response = _set(client, admin, admin.id, role)
    assert response.status_code == 409
    assert "another admin" in response.json()["detail"]
    assert client.get("/people/me", headers=admin.headers).json()["role"] == ROLE_ADMIN


def test_the_last_admin_can_never_be_demoted(client: TestClient, admin: Account) -> None:
    """Only admins change roles and nobody changes their own, so a lone admin is safe."""
    assert _set(client, admin, admin.id, ROLE_MEMBER).status_code == 409
    users = client.get("/users", headers=admin.headers).json()
    assert [u["role"] for u in users].count(ROLE_ADMIN) == 1


def test_two_admins_can_demote_each_other_but_not_themselves(
    client: TestClient, admin: Account, lead: Account
) -> None:
    _set(client, admin, lead.id, ROLE_ADMIN)
    assert _set(client, lead, admin.id, ROLE_MEMBER).status_code == 200
    # Ada is now a member and can no longer manage roles at all.
    assert _set(client, admin, lead.id, ROLE_MEMBER).status_code == 403


@pytest.mark.parametrize("who", ["lead", "member"])
def test_non_admins_cannot_change_roles(
    client: TestClient, request: pytest.FixtureRequest, admin: Account, who: str
) -> None:
    account: Account = request.getfixturevalue(who)
    assert _set(client, account, account.id, ROLE_ADMIN).status_code == 403
    assert _set(client, account, admin.id, ROLE_MEMBER).status_code == 403


@pytest.mark.parametrize("bad", ["superuser", "ADMIN", "", None, 1])
def test_unknown_roles_are_rejected(
    client: TestClient, admin: Account, member: Account, bad: object
) -> None:
    response = client.put(f"/users/{member.id}/role", json={"role": bad}, headers=admin.headers)
    assert response.status_code == 422


def test_changing_a_missing_user_is_404(client: TestClient, admin: Account) -> None:
    assert _set(client, admin, 99999, ROLE_MEMBER).status_code == 404


def test_changing_roles_requires_login(client: TestClient) -> None:
    assert client.put("/users/1/role", json={"role": ROLE_ADMIN}).status_code == 401


def test_a_demoted_team_lead_still_leads_their_team(
    client: TestClient,
    admin: Account,
    lead: Account,
    outsider: Account,
    team: dict,
    user_headers: Callable[..., dict[str, str]],
) -> None:
    """Team leadership is per-team and survives an app-wide role change."""
    _set(client, admin, lead.id, ROLE_MEMBER)
    response = client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=lead.headers
    )
    assert response.status_code == 201
