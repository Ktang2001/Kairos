"""Rare paths that ordinary use never reaches, but that must not turn into a
500 or a crash when they do: two people racing for the same email or team
name, corrupt stored values, and so on.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from server.api import auth as auth_api
from server.api.protection import BodySizeLimitMiddleware, _BodyTooLarge, _is_loopback
from server.db import session as db_session
from server.services import auth_service, password_service, session_service, team_service
from shared.roles import ROLE_PROJECT_LEAD
from tests.server.conftest import TEST_PASSWORD


@pytest.fixture
def db(session_factory: sessionmaker[Session], seeded_roles: None):
    session = session_factory()
    yield session
    session.close()


def _make_user(db: Session, email: str, role: str = "member"):
    return auth_service.register_user(
        db, name=email.split("@")[0], email=email, password=TEST_PASSWORD, role_name=role
    )


# ------------------------------------------------------------- accounts


def test_an_unknown_role_is_refused(db: Session) -> None:
    with pytest.raises(auth_service.UnknownRole):
        _make_user(db, "a@example.com", role="emperor")


def test_two_registrations_racing_for_one_email_report_it_as_taken(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_user(db, "a@example.com")
    # The second request passed the "is it taken?" check before the first
    # committed; only the database's unique index stops it.
    monkeypatch.setattr(auth_service, "get_user_by_email", lambda _db, _email: None)
    with pytest.raises(auth_service.EmailAlreadyRegistered):
        _make_user(db, "a@example.com")


def test_registering_with_no_roles_in_the_database_is_a_clear_500(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_roles(*_args, **_kwargs):
        raise auth_service.UnknownRole("member")

    monkeypatch.setattr(auth_service, "register_user", no_roles)
    response = client.post(
        "/auth/register",
        json={"name": "A", "email": "a@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 500
    assert "no roles configured" in response.json()["detail"]


@pytest.mark.parametrize(
    ("seconds", "words"),
    [(1, "1 second"), (30, "30 seconds"), (60, "1 minute"), (61, "2 minutes")],
)
def test_lockout_waits_read_naturally(seconds: int, words: str) -> None:
    assert auth_api._wait_in_words(seconds) == words


def test_an_empty_token_is_no_session(db: Session) -> None:
    assert session_service.resolve_session(db, "") is None


def test_a_stored_hash_with_a_truncated_key_never_matches() -> None:
    stored = password_service.hash_password(TEST_PASSWORD)
    *head, _key = stored.split("$")
    corrupt = "$".join([*head, password_service._encode(b"short")])
    assert password_service.verify_password(TEST_PASSWORD, corrupt) is False


@pytest.mark.parametrize(
    ("r", "p"), [(0, 1), (999, 1), (8, 0), (8, 999)], ids=["r-0", "r-huge", "p-0", "p-huge"]
)
def test_a_stored_hash_with_corrupt_cost_settings_never_matches(r: int, p: int) -> None:
    # Checked before hashing: a huge r or p from a corrupt row would make the
    # server spend enormous memory or time on a single login.
    algorithm, n, _r, _p, salt, key = password_service.hash_password(TEST_PASSWORD).split("$")
    corrupt = "$".join([algorithm, n, str(r), str(p), salt, key])
    assert password_service.verify_password(TEST_PASSWORD, corrupt) is False


def test_signing_out_twice_keeps_the_first_sign_out_time(db: Session) -> None:
    user = _make_user(db, "a@example.com")
    session, _token = session_service.create_session(db, user)
    session_service.revoke_session(db, session)
    first = session.revoked_at
    session_service.revoke_session(db, session)
    assert session.revoked_at == first


def test_get_db_outside_a_request_gives_an_ordinary_session(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Start-up uses it this way; pointed at the test database, never kairos.db.
    monkeypatch.setattr(db_session, "SessionLocal", session_factory)
    sessions = db_session.get_db()
    assert isinstance(next(sessions), Session)
    sessions.close()


# ---------------------------------------------------------------- teams


def test_two_teams_racing_for_one_name_report_it_as_taken(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    lead = _make_user(db, "lead@example.com", ROLE_PROJECT_LEAD)
    team_service.create_team(db, name="Alpha", creator=lead)
    monkeypatch.setattr(team_service, "_name_taken", lambda *_args, **_kwargs: False)
    with pytest.raises(team_service.TeamNameTaken):
        team_service.create_team(db, name="Alpha", creator=lead)


def test_a_duplicate_membership_refused_by_the_database_is_reported_as_a_member(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two simultaneous adds of the same person both pass the "already on the
    # team?" check; the table's primary key refuses the second insert.
    lead = _make_user(db, "lead@example.com", ROLE_PROJECT_LEAD)
    _make_user(db, "max@example.com")
    team = team_service.create_team(db, name="Alpha", creator=lead)

    def refused() -> None:
        raise IntegrityError("INSERT INTO team_members", {}, Exception("UNIQUE constraint failed"))

    monkeypatch.setattr(db, "commit", refused)
    with pytest.raises(team_service.AlreadyMember):
        team_service.add_member(db, team.id, lead, email="max@example.com")


# ------------------------------------------------------- request limits


def test_loopback_check_rejects_a_missing_address() -> None:
    assert _is_loopback(None) is False


def test_an_oversized_body_after_the_reply_started_is_not_answered_twice() -> None:
    async def app(_scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()  # the body turns out to be too big only now

    sent: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"x" * 20, "more_body": False}

    async def send(message: dict) -> None:
        sent.append(message)

    middleware = BodySizeLimitMiddleware(app, max_bytes=10)
    with pytest.raises(_BodyTooLarge):
        asyncio.run(middleware({"type": "http", "headers": [], "path": "/"}, receive, send))
    # A second "response start" (the 413) would be a protocol error.
    assert [message["type"] for message in sent] == ["http.response.start"]


def _run_middleware(app, messages: list[dict]) -> list[dict]:
    sent: list[dict] = []
    incoming = iter(messages)

    async def receive() -> dict:
        return next(incoming)

    async def send(message: dict) -> None:
        sent.append(message)

    middleware = BodySizeLimitMiddleware(app, max_bytes=10)
    asyncio.run(middleware({"type": "http", "headers": [], "path": "/"}, receive, send))
    return sent


def test_a_streamed_body_that_grows_too_large_gets_a_413() -> None:
    # No Content-Length up front, so the size is only known while reading.
    async def app(_scope, receive, _send) -> None:
        while (await receive()).get("more_body"):
            pass

    sent = _run_middleware(
        app,
        [
            {"type": "http.request", "body": b"x" * 6, "more_body": True},
            {"type": "http.request", "body": b"x" * 6, "more_body": False},
        ],
    )
    assert sent[0]["status"] == 413


def test_a_client_disconnecting_is_passed_through_untouched() -> None:
    seen: list[str] = []

    async def app(_scope, receive, send) -> None:
        seen.append((await receive())["type"])
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    sent = _run_middleware(app, [{"type": "http.disconnect"}])
    assert seen == ["http.disconnect"]
    assert sent[0]["status"] == 204
