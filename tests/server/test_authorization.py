"""Tests for role-based authorisation (context.md goal #2).

``/auth/purge-expired-sessions`` is the probe: it is the one route that demands
a specific role, which makes it the cheapest place to prove that the
``require_role`` dependency really does reject people.
"""

from collections.abc import Callable

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from server.services import auth_service
from shared.roles import ROLE_ADMIN, ROLE_PROJECT_LEAD

PURGE_URL = "/auth/purge-expired-sessions"


def _set_role(
    session_factory: sessionmaker[Session],
    email: str,
    role_name: str,
) -> None:
    """Change a user's role directly, the way a future admin route would."""
    db = session_factory()
    try:
        user = auth_service.get_user_by_email(db, email)
        assert user is not None, f"no user {email!r} to promote"
        role = auth_service.get_role_by_name(db, role_name)
        assert role is not None, f"no role {role_name!r}"
        user.role_id = role.id
        db.commit()
    finally:
        db.close()


def test_a_member_is_forbidden_from_an_admin_route(
    client: TestClient, auth_headers: Callable[..., dict[str, str]]
) -> None:
    headers = auth_headers(email="member@example.com")

    response = client.post(PURGE_URL, headers=headers)

    assert response.status_code == 403
    assert ROLE_ADMIN in response.json()["detail"]


def test_an_admin_may_call_an_admin_route(
    client: TestClient,
    auth_headers: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    headers = auth_headers(email="boss@example.com")
    _set_role(session_factory, "boss@example.com", ROLE_ADMIN)

    response = client.post(PURGE_URL, headers=headers)

    assert response.status_code == 200, response.text
    assert "purged" in response.json()


def test_a_project_lead_is_forbidden_from_an_admin_route(
    client: TestClient,
    auth_headers: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    """A privileged-but-not-top role must still be refused."""
    headers = auth_headers(email="lead@example.com")
    _set_role(session_factory, "lead@example.com", ROLE_PROJECT_LEAD)

    response = client.post(PURGE_URL, headers=headers)

    assert response.status_code == 403


def test_an_anonymous_caller_gets_401_not_403(client: TestClient) -> None:
    """401 means "identify yourself"; 403 means "you may not". A caller with no
    credentials must get the first, or the client cannot tell whether retrying
    with a login would help."""
    response = client.post(PURGE_URL)

    assert response.status_code == 401


def test_a_invalid_token_gets_401_not_403(client: TestClient) -> None:
    response = client.post(PURGE_URL, headers={"Authorization": "Bearer nonsense"})

    assert response.status_code == 401


def test_a_role_change_applies_to_an_existing_token(
    client: TestClient,
    auth_headers: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    """The role is read per request, so promoting someone takes effect at once
    rather than only at their next login."""
    headers = auth_headers(email="promoted@example.com")
    assert client.post(PURGE_URL, headers=headers).status_code == 403

    _set_role(session_factory, "promoted@example.com", ROLE_ADMIN)

    assert client.post(PURGE_URL, headers=headers).status_code == 200


def test_demoting_an_admin_takes_effect_immediately(
    client: TestClient,
    auth_headers: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    """The mirror image: removing a role must not wait for the token to expire."""
    headers = auth_headers(email="demoted@example.com")
    _set_role(session_factory, "demoted@example.com", ROLE_ADMIN)
    assert client.post(PURGE_URL, headers=headers).status_code == 200

    _set_role(session_factory, "demoted@example.com", "member")

    assert client.post(PURGE_URL, headers=headers).status_code == 403
