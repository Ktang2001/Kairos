"""Tests for session handling: /auth/me, /auth/logout, expiry, and storage."""

from collections.abc import Callable
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from server.models.session import Session as LoginSession
from server.services import session_service
from server.services.auth_service import utcnow
from tests.server.conftest import TEST_PASSWORD

LOGIN_URL = "/auth/login"
ME_URL = "/auth/me"
LOGOUT_URL = "/auth/logout"


def _all_sessions(session_factory: sessionmaker[Session]) -> list[LoginSession]:
    db = session_factory()
    try:
        return list(db.scalars(select(LoginSession)))
    finally:
        db.close()


def _expire_all_sessions(session_factory: sessionmaker[Session]) -> None:
    """Backdate every session so it is past its expiry."""
    db = session_factory()
    try:
        for login_session in db.scalars(select(LoginSession)):
            login_session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    finally:
        db.close()


def test_me_returns_the_signed_in_user(
    client: TestClient, auth_headers: Callable[..., dict[str, str]]
) -> None:
    headers = auth_headers(email="kaleb@example.com", name="Kaleb")

    response = client.get(ME_URL, headers=headers)

    assert response.status_code == 200, response.text
    assert response.json()["email"] == "kaleb@example.com"
    assert response.json()["name"] == "Kaleb"
    assert response.json()["role"] == "member"


def test_me_without_a_token_is_rejected(client: TestClient) -> None:
    response = client.get(ME_URL)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


def test_me_with_a_garbage_token_is_rejected(client: TestClient) -> None:
    response = client.get(ME_URL, headers={"Authorization": "Bearer not-a-real-token"})

    assert response.status_code == 401


def test_me_with_the_wrong_auth_scheme_is_rejected(client: TestClient) -> None:
    """A Basic header must not be mistaken for a bearer token."""
    response = client.get(ME_URL, headers={"Authorization": "Basic YWRtaW46YWRtaW4="})

    assert response.status_code == 401


def test_me_with_an_empty_bearer_token_is_rejected(client: TestClient) -> None:
    response = client.get(ME_URL, headers={"Authorization": "Bearer "})

    assert response.status_code == 401


def test_the_raw_token_is_never_stored(
    client: TestClient,
    register: Callable[..., dict],
    session_factory: sessionmaker[Session],
) -> None:
    """Only the hash belongs in the database, so a stolen file is not a login."""
    token = register(email="kaleb@example.com")["token"]

    stored = [login_session.token_hash for login_session in _all_sessions(session_factory)]

    assert token not in stored
    assert session_service.hash_token(token) in stored


def test_login_adds_one_session_row(
    client: TestClient,
    register: Callable[..., dict],
    session_factory: sessionmaker[Session],
) -> None:
    register(email="kaleb@example.com")
    before = len(_all_sessions(session_factory))

    client.post(LOGIN_URL, json={"email": "kaleb@example.com", "password": TEST_PASSWORD})

    assert len(_all_sessions(session_factory)) == before + 1


def test_logout_invalidates_the_token(
    client: TestClient, auth_headers: Callable[..., dict[str, str]]
) -> None:
    headers = auth_headers(email="kaleb@example.com")
    assert client.get(ME_URL, headers=headers).status_code == 200

    assert client.post(LOGOUT_URL, headers=headers).status_code == 204
    assert client.get(ME_URL, headers=headers).status_code == 401


def test_logout_twice_is_rejected_the_second_time(
    client: TestClient, auth_headers: Callable[..., dict[str, str]]
) -> None:
    headers = auth_headers(email="kaleb@example.com")
    assert client.post(LOGOUT_URL, headers=headers).status_code == 204

    assert client.post(LOGOUT_URL, headers=headers).status_code == 401


def test_logout_only_affects_the_session_it_was_given(
    client: TestClient, register: Callable[..., dict]
) -> None:
    """Signing out on one machine must not sign the other machine out."""
    register(email="kaleb@example.com")
    credentials = {"email": "kaleb@example.com", "password": TEST_PASSWORD}

    first = client.post(LOGIN_URL, json=credentials).json()["token"]
    second = client.post(LOGIN_URL, json=credentials).json()["token"]

    client.post(LOGOUT_URL, headers={"Authorization": f"Bearer {first}"})

    assert client.get(ME_URL, headers={"Authorization": f"Bearer {first}"}).status_code == 401
    assert client.get(ME_URL, headers={"Authorization": f"Bearer {second}"}).status_code == 200


def test_an_expired_session_is_rejected(
    client: TestClient,
    auth_headers: Callable[..., dict[str, str]],
    session_factory: sessionmaker[Session],
) -> None:
    headers = auth_headers(email="kaleb@example.com")
    assert client.get(ME_URL, headers=headers).status_code == 200

    _expire_all_sessions(session_factory)

    assert client.get(ME_URL, headers=headers).status_code == 401


def test_purging_removes_expired_sessions_but_keeps_live_ones(
    client: TestClient,
    register: Callable[..., dict],
    session_factory: sessionmaker[Session],
) -> None:
    register(email="kaleb@example.com")
    credentials = {"email": "kaleb@example.com", "password": TEST_PASSWORD}
    client.post(LOGIN_URL, json=credentials)  # a session that will be expired

    db = session_factory()
    try:
        live = db.scalars(select(LoginSession)).first()
        for login_session in db.scalars(select(LoginSession)):
            login_session.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
        # Keep exactly one session alive so the assertion below distinguishes
        # "deleted the expired rows" from "deleted everything".
        live.expires_at = utcnow() + timedelta(days=1)
        db.commit()

        purged = session_service.purge_expired_sessions(db)
        remaining = list(db.scalars(select(LoginSession)))
    finally:
        db.close()

    assert purged == 1
    assert remaining == [live]


def test_a_fresh_session_is_valid_and_unrevoked(
    client: TestClient,
    register: Callable[..., dict],
    session_factory: sessionmaker[Session],
) -> None:
    """A session must start usable: expires in the future, not revoked."""
    register(email="kaleb@example.com")

    sessions = _all_sessions(session_factory)

    assert len(sessions) == 1
    assert sessions[0].expires_at > utcnow()
    assert sessions[0].revoked_at is None
