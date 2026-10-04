"""Tests for the teams/users side of ``ApiClient`` (the ``_request`` style): it
talks to the real API (``live_server``), sends the session token, and turns
every failure into an ``ApiError`` with a message fit to show.
"""

import httpx
import pytest

from client.api_client import ApiClient, ApiError, is_connection_error
from shared.roles import ROLE_ADMIN, ROLE_PROJECT_LEAD
from tests.client.conftest import SETUP_TIMEOUT, TEST_PASSWORD, set_live_role, unique_email


def _signed_in(live_server: str, name: str, role: str | None = None) -> ApiClient:
    """Sign up through /auth/signup and return a client holding the token."""
    email = unique_email(name.lower())
    body = httpx.post(
        f"{live_server}/auth/signup",
        json={"name": name, "email": email, "password": TEST_PASSWORD},
        timeout=SETUP_TIMEOUT,
    ).json()
    if role:
        set_live_role(email, role)
    return ApiClient(base_url=live_server, token=body["token"], user_id=body["id"])


def test_me_reports_the_current_role(live_server: str) -> None:
    client = _signed_in(live_server, "Max")
    assert client.me()["role"] == "member"


def test_teams_round_trip(live_server: str) -> None:
    lead = _signed_in(live_server, "Lena", ROLE_PROJECT_LEAD)
    name = f"Round trip {unique_email()}"
    team = lead.create_team(name)
    assert team["name"] == name
    assert [t["name"] for t in lead.list_teams()] == [name]
    assert lead.get_team(team["id"])["lead"]["id"] == lead.user_id
    lead.rename_team(team["id"], name + " 2")
    lead.delete_team(team["id"])
    assert lead.list_teams() == []


def test_a_refusal_carries_the_servers_message_and_status(live_server: str) -> None:
    member = _signed_in(live_server, "Max")
    with pytest.raises(ApiError) as error:
        member.create_team("Not allowed")
    assert error.value.status_code == 403
    assert "Requires one of" in error.value.message


def test_an_admin_cannot_change_their_own_role(live_server: str) -> None:
    admin = _signed_in(live_server, "Ada", ROLE_ADMIN)
    with pytest.raises(ApiError) as error:
        admin.set_role(admin.user_id, "member")
    assert error.value.status_code == 409
    assert "can't change your own role" in error.value.message


def test_an_unreachable_server_is_a_connection_error(dead_server: str) -> None:
    client = ApiClient(base_url=dead_server, token="t", user_id=1)
    with pytest.raises(ApiError) as error:
        client.list_teams()
    assert error.value.status_code is None
    assert is_connection_error(error.value.message)


def test_test_messages_are_sent_as_the_signed_in_user(live_server: str) -> None:
    client = _signed_in(live_server, "Max")
    sent = client.send_message(sender="Someone else", content="hello")
    assert sent["sender"] == "Max"  # the server ignores the claimed sender
