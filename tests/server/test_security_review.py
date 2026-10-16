"""Regression tests for the security review of 2026-10-16.

* Login tokens are stored hashed, so a copied database signs nobody in.
* Wrong passwords lock an account for longer each time (30 s doubling to 15 min).
* Login tokens never appear in uvicorn's log lines.
* People search treats % and _ literally.
"""

import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from server import log_redaction
from server.models.session import Session
from server.services import auth_service, session_service
from tests.server.conftest import TEST_PASSWORD, auth_headers

# --------------------------------------------------------- hashed tokens


def test_the_database_holds_only_the_tokens_hash(client: TestClient, register, db_session) -> None:
    token = register(email="hash@example.com")["token"]
    stored = list(db_session.scalars(select(Session.token)))
    assert token not in stored
    assert session_service.hash_token(token) in stored


def test_a_stored_value_copied_from_the_database_does_not_sign_in(
    client: TestClient, register, db_session
) -> None:
    """What someone holding a leaked database would try."""
    register(email="leak@example.com")
    [stored] = list(db_session.scalars(select(Session.token)))
    assert client.get("/people/me", headers=auth_headers(stored)).status_code == 401


def test_the_real_token_still_works_and_logout_ends_it(client: TestClient, register) -> None:
    token = register(email="real@example.com")["token"]
    assert client.get("/people/me", headers=auth_headers(token)).status_code == 200
    assert client.post("/auth/logout", headers=auth_headers(token)).status_code == 204
    assert client.get("/people/me", headers=auth_headers(token)).status_code == 401


def test_a_raw_token_left_from_before_the_change_no_longer_signs_in(
    client: TestClient, make_user, db_session
) -> None:
    """Rows written before hashing hold raw tokens; the migration deletes them,
    and even if one survived, a hashed lookup can never match it."""
    user = make_user("Old", "old@example.com")
    db_session.add(
        Session(
            token="raw-token-from-old-database",
            user_id=user.id,
            expires_at=session_service.create_session(db_session, user.id).expires_at,
        )
    )
    db_session.commit()
    headers = auth_headers("raw-token-from-old-database")
    assert client.get("/people/me", headers=headers).status_code == 401


# ------------------------------------------------------ escalating lockout


@pytest.fixture
def clock(monkeypatch) -> list[float]:
    """A fake ``time.monotonic`` for auth_service; append to move time on."""
    now = [1000.0]
    monkeypatch.setattr(auth_service.time, "monotonic", lambda: now[0])
    return now


def _login(client: TestClient, password: str) -> int:
    return client.post(
        "/auth/login", json={"email": "lock@example.com", "password": password}
    ).status_code


def test_lockouts_grow_with_each_further_failure(client: TestClient, register, clock) -> None:
    register(email="lock@example.com")
    for _ in range(5):
        assert _login(client, "wrong-password") == 401
    assert _login(client, TEST_PASSWORD) == 429  # first lock: 30 s

    clock[0] += 31
    assert _login(client, "wrong-password") == 401  # sixth failure: 60 s lock
    clock[0] += 31
    assert _login(client, TEST_PASSWORD) == 429
    clock[0] += 30
    assert _login(client, "wrong-password") == 401  # seventh: 120 s
    clock[0] += 100
    response = client.post(
        "/auth/login", json={"email": "lock@example.com", "password": TEST_PASSWORD}
    )
    assert response.status_code == 429
    assert "try again in" in response.json()["detail"]


def test_the_lockout_is_capped_at_fifteen_minutes(client: TestClient, register, clock) -> None:
    register(email="lock@example.com")
    for _ in range(5):
        _login(client, "wrong-password")
    # Wait out each lock (30, 60, 120, 240, 480 s) and fail again: about 15
    # minutes in all, well inside the hour failures are remembered.
    for extra in range(5):
        clock[0] += auth_service._COOLDOWN_SECONDS * 2**extra + 1
        assert _login(client, "wrong-password") == 401
    # Ten failures would mean a 960 s lock; it is capped at 900 s.
    clock[0] += auth_service._MAX_LOCKOUT_SECONDS - 5
    assert _login(client, TEST_PASSWORD) == 429
    clock[0] += 10
    assert _login(client, TEST_PASSWORD) == 200


def test_success_clears_the_failures(client: TestClient, register, clock) -> None:
    register(email="lock@example.com")
    for _ in range(4):
        _login(client, "wrong-password")
    assert _login(client, TEST_PASSWORD) == 200
    for _ in range(4):
        assert _login(client, "wrong-password") == 401
    assert _login(client, TEST_PASSWORD) == 200


def test_failures_are_forgotten_after_an_hour(client: TestClient, register, clock) -> None:
    register(email="lock@example.com")
    for _ in range(5):
        _login(client, "wrong-password")
    clock[0] += auth_service._FAILURE_MEMORY_SECONDS + 1
    assert _login(client, TEST_PASSWORD) == 200


def test_guessing_at_many_made_up_emails_cannot_grow_the_table_forever(monkeypatch, clock) -> None:
    monkeypatch.setattr(auth_service, "_MAX_TRACKED_EMAILS", 50)
    for i in range(50):
        auth_service._record_failed_attempt(f"nobody{i}@example.com")
    clock[0] += auth_service._FAILURE_MEMORY_SECONDS + 1
    auth_service._record_failed_attempt("one-more@example.com")
    assert list(auth_service._failed_login_attempts) == ["one-more@example.com"]


# ------------------------------------------------------------ log redaction


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('"WebSocket /ws/chat?token=abc.DEF-123_x" 101', '"WebSocket /ws/chat?token=[hidden]" 101'),
        ("/ws/chat?a=1&token=secret&b=2", "/ws/chat?a=1&token=[hidden]&b=2"),
        ("GET /teams 200", "GET /teams 200"),
    ],
)
def test_tokens_are_hidden_in_log_text(line: str, expected: str) -> None:
    assert log_redaction.redact(line) == expected


def test_uvicorn_log_records_have_tokens_hidden(caplog) -> None:
    log_redaction.install()
    log_redaction.install()  # twice is harmless
    logger = logging.getLogger("uvicorn.error")
    assert sum(isinstance(f, log_redaction.RedactTokens) for f in logger.filters) == 1
    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        logger.info('%s - "WebSocket %s" [accepted]', "127.0.0.1:5000", "/ws/chat?token=s3cret")
        logging.getLogger("uvicorn.access").info(
            '%(client)s "%(path)s"', {"client": "1.2.3.4", "path": "/ws/chat?token=s3cret"}
        )
    assert "s3cret" not in caplog.text
    assert "token=[hidden]" in caplog.text


# ------------------------------------------------------------ people search


@pytest.mark.parametrize("query", ["%", "_", "%%", "_@%"])
def test_search_wildcards_match_only_themselves(client: TestClient, make_user, query: str) -> None:
    alice = make_user("Alice", "alice@example.com")
    make_user("Bob", "bob@example.com")
    response = client.get("/people/search", params={"q": query}, headers=auth_headers(alice.token))
    assert response.status_code == 200
    assert response.json() == []


def test_a_name_containing_an_underscore_is_still_found(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    make_user("dev_ops", "ops@example.com")
    response = client.get("/people/search", params={"q": "v_o"}, headers=auth_headers(alice.token))
    assert [p["name"] for p in response.json()] == ["dev_ops"]


# ------------------------------------------------------------ sign-up limits


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("password", "p" * 129),
        ("password", "p" * 1_000_000),
        ("name", "n" * 101),
        ("name", "\u200b\u2060"),
        ("email", "a" * 250 + "@example.com"),
        ("email", "no-at-sign.example.com"),
        ("email", "two@@example.com"),
    ],
    # Short ids: pytest puts the test id in an environment variable, and a 1 MB
    # value is longer than Windows allows.
    ids=[
        "password-129",
        "password-1MB",
        "name-101",
        "name-invisible",
        "email-too-long",
        "email-no-at",
        "email-two-ats",
    ],
)
def test_sign_up_enforces_the_shared_limits(client: TestClient, field: str, value: str) -> None:
    body = {"name": "Eve", "email": "eve@example.com", "password": TEST_PASSWORD, field: value}
    response = client.post("/auth/signup", json=body)
    assert response.status_code in (400, 413, 422), response.text


def test_invisible_characters_are_removed_from_account_names(client: TestClient) -> None:
    body = {"name": "E\u200bve\u202e", "email": "eve@example.com", "password": TEST_PASSWORD}
    response = client.post("/auth/signup", json=body)
    assert response.status_code == 200
    assert response.json()["name"] == "Eve"


def test_a_128_character_password_works(client: TestClient) -> None:
    password = "p" * 128
    body = {"name": "Eve", "email": "eve@example.com", "password": password}
    assert client.post("/auth/signup", json=body).status_code == 200
    login = client.post("/auth/login", json={"email": "eve@example.com", "password": password})
    assert login.status_code == 200


def test_an_unknown_email_costs_a_full_password_check(
    client: TestClient, register, monkeypatch
) -> None:
    """So the reply time doesn't reveal which emails have accounts."""
    register(email="real@example.com")
    checked: list[str] = []
    real_verify = auth_service.verify_password
    monkeypatch.setattr(
        auth_service,
        "verify_password",
        lambda password, stored: checked.append(stored) or real_verify(password, stored),
    )
    client.post("/auth/login", json={"email": "nobody@example.com", "password": "wrong-pass"})
    client.post("/auth/login", json={"email": "real@example.com", "password": "wrong-pass"})
    assert len(checked) == 2
    assert checked[0] == auth_service._dummy_hash()
