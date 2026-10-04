"""Rare paths that ordinary use never reaches, but that must not turn into a
500 or a crash when they do: two people racing for the same team name or
membership, oversized or interrupted request bodies, and so on.
"""

import asyncio

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from server.api.protection import BodySizeLimitMiddleware, _BodyTooLarge, _is_loopback
from server.db import session as db_session
from server.services import auth_service, team_service
from shared.roles import ROLE_PROJECT_LEAD
from tests.server.conftest import TEST_PASSWORD


@pytest.fixture
def db(session_factory: sessionmaker[Session], seeded_roles: None):
    session = session_factory()
    yield session
    session.close()


def _make_user(db: Session, email: str, role: str = "member"):
    """Sign a user up (Kaleb's create_user), then give them ``role``."""
    user = auth_service.create_user(
        db, name=email.split("@")[0], email=email, password=TEST_PASSWORD
    )
    user.role_id = auth_service.get_role_by_name(db, role).id
    db.commit()
    return auth_service.get_user_by_email(db, email)


# ------------------------------------------------------------- database


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


def test_a_team_deleted_by_someone_else_mid_request_is_not_found(db: Session) -> None:
    # The write lock ends at a commit; a simultaneous delete can land before
    # the re-read that builds the reply. That is a 404, not a crash.
    with pytest.raises(team_service.TeamNotFound):
        team_service._reload(db, 999_999)


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
