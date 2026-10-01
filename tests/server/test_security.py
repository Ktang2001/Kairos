"""Tests for the fixes from the security audit.

1  login lockout                 6  request size limit
2  weak passwords rejected       7  sign out everywhere
3-4 messages need login           8  sessions per user capped
   (see test_messages.py)        9  oversized ids
5  plain-text message windows    10 invisible characters stripped from names
   (see tests/client)            12 API docs only from the host computer
                                 14 no --password on the seed command line
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from server import seed
from server.api.protection import MAX_BODY_BYTES
from server.main import app
from server.models.session import Session as SessionRow
from server.services import auth_service, login_throttle
from server.services.login_throttle import (
    FAILURES_BEFORE_ADDRESS_LOCK,
    FAILURES_BEFORE_LOCK,
    FIRST_LOCK_SECONDS,
    MAX_LOCK_SECONDS,
    LoginThrottle,
    lock_seconds,
)
from server.services.session_service import MAX_SESSIONS_PER_USER
from tests.server.conftest import TEST_PASSWORD


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> Iterator[FakeClock]:
    """Swap the app's throttle for one on a clock the test controls."""
    fake = FakeClock()
    original = app.state.login_throttle
    app.state.login_throttle = LoginThrottle(clock=fake)
    yield fake
    app.state.login_throttle = original


def _login(client: TestClient, email: str, password: str):
    return client.post("/auth/login", json={"email": email, "password": password})


# ============================================================ 1. lockout


def test_lock_lengths_double_and_are_capped() -> None:
    t = FAILURES_BEFORE_LOCK
    assert lock_seconds(t - 1, t) == 0
    assert lock_seconds(t, t) == FIRST_LOCK_SECONDS
    assert lock_seconds(t + 1, t) == FIRST_LOCK_SECONDS * 2
    assert lock_seconds(t + 2, t) == FIRST_LOCK_SECONDS * 4
    assert lock_seconds(t + 50, t) == MAX_LOCK_SECONDS


def test_the_pair_locks_after_five_failures_and_unlocks_after_the_wait() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(clock=clock)
    for _ in range(FAILURES_BEFORE_LOCK - 1):
        throttle.record_failure("a@x.co", "10.0.0.5")
    assert throttle.retry_after("a@x.co", "10.0.0.5") == 0

    throttle.record_failure("a@x.co", "10.0.0.5")
    assert throttle.retry_after("a@x.co", "10.0.0.5") == FIRST_LOCK_SECONDS

    clock.advance(FIRST_LOCK_SECONDS)
    assert throttle.retry_after("a@x.co", "10.0.0.5") == 0


def test_another_computer_is_not_locked_out() -> None:
    """Guessing from your own machine must not lock the real owner out of theirs."""
    throttle = LoginThrottle(clock=FakeClock())
    for _ in range(FAILURES_BEFORE_LOCK + 3):
        throttle.record_failure("victim@x.co", "10.0.0.66")
    assert throttle.retry_after("victim@x.co", "10.0.0.66") > 0
    assert throttle.retry_after("victim@x.co", "10.0.0.5") == 0


def test_the_email_is_matched_ignoring_case_and_spaces() -> None:
    throttle = LoginThrottle(clock=FakeClock())
    for variant in ("a@x.co", "A@X.CO", " a@x.co ", "a@X.co", "A@x.co"):
        throttle.record_failure(variant, "10.0.0.5")
    assert throttle.retry_after("a@x.co", "10.0.0.5") > 0


def test_one_address_spraying_many_emails_gets_locked() -> None:
    throttle = LoginThrottle(clock=FakeClock())
    for i in range(FAILURES_BEFORE_ADDRESS_LOCK):
        throttle.record_failure(f"user{i}@x.co", "10.0.0.66")
    assert throttle.retry_after("someone-new@x.co", "10.0.0.66") > 0
    assert throttle.retry_after("someone-new@x.co", "10.0.0.5") == 0


def test_success_clears_the_pair_but_not_the_address_counter() -> None:
    throttle = LoginThrottle(clock=FakeClock())
    for _ in range(FAILURES_BEFORE_LOCK - 1):
        throttle.record_failure("a@x.co", "10.0.0.5")
    throttle.record_success("a@x.co", "10.0.0.5")
    throttle.record_failure("a@x.co", "10.0.0.5")
    assert throttle.retry_after("a@x.co", "10.0.0.5") == 0
    assert throttle._addresses["10.0.0.5"].failures == FAILURES_BEFORE_LOCK


def test_old_counters_are_forgotten() -> None:
    clock = FakeClock()
    throttle = LoginThrottle(clock=clock)
    throttle.record_failure("a@x.co", "10.0.0.5")
    clock.advance(login_throttle.FORGET_AFTER_SECONDS + login_throttle.PRUNE_EVERY_SECONDS + 1)
    throttle.record_failure("b@x.co", "10.0.0.9")  # triggers a prune
    assert ("a@x.co", "10.0.0.5") not in throttle._pairs


def test_the_api_returns_429_with_retry_after(
    client: TestClient, register: Callable[..., dict], clock: FakeClock
) -> None:
    register(email="nick@example.com")
    codes = [_login(client, "nick@example.com", f"wrong-{i}").status_code for i in range(5)]
    assert codes == [401] * 5

    locked = _login(client, "nick@example.com", TEST_PASSWORD)  # even the right password
    assert locked.status_code == 429
    assert locked.headers["Retry-After"] == str(FIRST_LOCK_SECONDS)
    assert locked.json()["detail"] == "Too many failed sign-in attempts. Try again in 1 minute."

    clock.advance(FIRST_LOCK_SECONDS)
    assert _login(client, "nick@example.com", TEST_PASSWORD).status_code == 200


def test_a_locked_attempt_does_no_password_work(
    client: TestClient,
    register: Callable[..., dict],
    clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """So the lock also stops login being used to burn the host's CPU and memory."""
    register(email="nick@example.com")
    for i in range(FAILURES_BEFORE_LOCK):
        _login(client, "nick@example.com", f"wrong-{i}")

    calls = []
    real = auth_service.authenticate
    monkeypatch.setattr(
        auth_service, "authenticate", lambda *a, **k: calls.append(1) or real(*a, **k)
    )
    for _ in range(10):
        assert _login(client, "nick@example.com", "anything").status_code == 429
    assert calls == []


def test_unknown_emails_lock_too(client: TestClient, clock: FakeClock) -> None:
    """Otherwise "locks" vs "never locks" would reveal which emails exist."""
    for i in range(FAILURES_BEFORE_LOCK):
        _login(client, "ghost@example.com", f"wrong-{i}")
    assert _login(client, "ghost@example.com", "again").status_code == 429


def test_a_good_login_resets_the_count(
    client: TestClient, register: Callable[..., dict], clock: FakeClock
) -> None:
    register(email="nick@example.com")
    for round_ in range(3):
        for i in range(FAILURES_BEFORE_LOCK - 1):
            assert _login(client, "nick@example.com", f"typo-{round_}-{i}").status_code == 401
        assert _login(client, "nick@example.com", TEST_PASSWORD).status_code == 200


# ===================================================== 2. weak passwords


@pytest.mark.parametrize(
    ("password", "fragment"),
    [
        ("password", "too common"),
        ("Password123", "too common"),
        ("12345678", "too common"),
        ("aaaaaaaa", "one character repeated"),
        ("victim@example.com", "your email"),
        ("victim12", "your email"),  # the part before the @
        ("Victor Smith", "your name"),
    ],
)
def test_guessable_passwords_are_rejected(client: TestClient, password: str, fragment: str) -> None:
    response = client.post(
        "/auth/register",
        json={
            "name": "Victor Smith",
            "email": "victim12@example.com" if password == "victim12" else "victim@example.com",
            "password": password,
        },
    )
    assert response.status_code == 422
    assert fragment in response.text


def test_a_strong_password_is_accepted(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"name": "Victor", "email": "v@example.com", "password": "tangerine-ladder-77"},
    )
    assert response.status_code == 201


def test_existing_accounts_with_weak_passwords_can_still_sign_in(
    client: TestClient, session_factory: sessionmaker[Session]
) -> None:
    """The rule applies to new passwords; nobody is locked out of an old one."""
    db = session_factory()
    try:
        auth_service.register_user(db, name="Old", email="old@example.com", password="password")
    finally:
        db.close()
    assert _login(client, "old@example.com", "password").status_code == 200


# ================================================= 6. request size limit


def test_a_body_over_the_limit_is_refused_by_its_declared_length(client: TestClient) -> None:
    big = b'{"email":"a@b.co","password":"' + b"x" * MAX_BODY_BYTES + b'"}'
    response = client.post("/auth/login", content=big, headers={"content-type": "application/json"})
    assert response.status_code == 413


def test_a_streamed_body_without_a_length_is_cut_off(client: TestClient) -> None:
    def chunks() -> Iterator[bytes]:
        yield b'{"email":"a@b.co","password":"'
        for _ in range(3 * MAX_BODY_BYTES // 65536):
            yield b"x" * 65536
        yield b'"}'

    response = client.post(
        "/auth/login", content=chunks(), headers={"content-type": "application/json"}
    )
    assert response.status_code == 413


def test_a_body_just_under_the_limit_is_still_processed(client: TestClient) -> None:
    body = b'{"email":"a@b.co","password":"' + b"x" * (MAX_BODY_BYTES - 100) + b'"}'
    response = client.post(
        "/auth/login", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422  # too long a password, but read and validated


def test_a_bogus_content_length_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/auth/login",
        content=b"{}",
        headers={"content-type": "application/json", "content-length": "lots"},
    )
    assert response.status_code == 400


# ============================================== 7. sign out everywhere


def test_logout_all_ends_every_session(client: TestClient, register: Callable[..., dict]) -> None:
    register(email="nick@example.com")
    tokens = [_login(client, "nick@example.com", TEST_PASSWORD).json()["token"] for _ in range(3)]

    first = {"Authorization": f"Bearer {tokens[0]}"}
    assert client.post("/auth/logout-all", headers=first).status_code == 204

    for token in tokens:
        assert (
            client.get("/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
        )


def test_logout_all_leaves_other_users_alone(
    client: TestClient, auth_headers: Callable[..., dict[str, str]]
) -> None:
    nick = auth_headers(email="nick@example.com")
    kaleb = auth_headers(email="kaleb@example.com")
    client.post("/auth/logout-all", headers=nick)
    assert client.get("/auth/me", headers=kaleb).status_code == 200


def test_logout_all_requires_login(client: TestClient) -> None:
    assert client.post("/auth/logout-all").status_code == 401


# ========================================== 8. sessions per user capped


def test_only_the_newest_sessions_stay_live(
    client: TestClient, register: Callable[..., dict], session_factory: sessionmaker[Session]
) -> None:
    register(email="nick@example.com")  # session 1
    tokens = [
        _login(client, "nick@example.com", TEST_PASSWORD).json()["token"]
        for _ in range(MAX_SESSIONS_PER_USER + 4)
    ]

    db = session_factory()
    try:
        live = db.scalar(
            select(func.count()).select_from(SessionRow).where(SessionRow.revoked_at.is_(None))
        )
    finally:
        db.close()
    assert live == MAX_SESSIONS_PER_USER

    newest, oldest = tokens[-1], tokens[0]
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {newest}"}).status_code == 200
    assert client.get("/auth/me", headers={"Authorization": f"Bearer {oldest}"}).status_code == 401


def test_the_cap_is_per_user(
    client: TestClient, register: Callable[..., dict], auth_headers: Callable[..., dict[str, str]]
) -> None:
    kaleb = auth_headers(email="kaleb@example.com")
    register(email="nick@example.com")
    for _ in range(MAX_SESSIONS_PER_USER + 2):
        _login(client, "nick@example.com", TEST_PASSWORD)
    assert client.get("/auth/me", headers=kaleb).status_code == 200


# ================================================== 9. oversized ids


@pytest.mark.parametrize("big", ["9223372036854775808", "99999999999999999999"])
def test_ids_beyond_64_bits_are_rejected_not_crashed(
    client: TestClient, auth_headers: Callable[..., dict[str, str]], big: str
) -> None:
    headers = auth_headers()
    for url in (f"/teams/{big}", f"/projects/{big}", f"/tasks/{big}"):
        response = client.get(url, headers=headers)
        assert response.status_code == 422, url
        assert response.json()["detail"] == "A number in the request is too large"


def test_the_largest_64_bit_id_is_just_not_found(
    client: TestClient, auth_headers: Callable[..., dict[str, str]]
) -> None:
    assert client.get("/teams/9223372036854775807", headers=auth_headers()).status_code == 404


# ======================================= 10. invisible characters in names


@pytest.mark.parametrize(
    "sneaky",
    ["\u202eAlice", "Ali\u200bce", "Alice\u200d", "\u2066Alice\u2069", "Alice\u0007"],
    ids=["rtl-override", "zero-width-space", "zero-width-joiner", "isolate", "bell"],
)
def test_invisible_characters_are_stripped_from_account_names(
    client: TestClient, sneaky: str
) -> None:
    response = client.post(
        "/auth/register",
        json={"name": sneaky, "email": "a@example.com", "password": TEST_PASSWORD},
    )
    assert response.json()["user"]["name"] == "Alice"


def test_a_name_of_only_invisible_characters_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"name": "\u200b\u200b", "email": "a@example.com", "password": TEST_PASSWORD},
    )
    assert response.status_code == 422


def test_accents_and_emoji_are_kept(client: TestClient) -> None:
    response = client.post(
        "/auth/register",
        json={"name": "Zoë 🎉", "email": "z@example.com", "password": TEST_PASSWORD},
    )
    assert response.json()["user"]["name"] == "Zoë 🎉"


def test_team_and_project_names_are_cleaned(client: TestClient, session_factory) -> None:
    lead = client.post(
        "/auth/register", json={"name": "L", "email": "l@example.com", "password": TEST_PASSWORD}
    ).json()
    db = session_factory()
    try:
        user = auth_service.get_user_by_email(db, "l@example.com")
        user.role_id = auth_service.get_role_by_name(db, "project_lead").id
        db.commit()
    finally:
        db.close()
    headers = {"Authorization": f"Bearer {lead['token']}"}

    team = client.post("/teams", json={"name": "Alp\u200bha"}, headers=headers).json()
    assert team["name"] == "Alpha"
    assert client.post("/teams", json={"name": "\u202eAlpha"}, headers=headers).status_code == 409
    project = client.post(
        f"/teams/{team['id']}/projects", json={"name": "\u202eWeb"}, headers=headers
    ).json()
    assert project["name"] == "Web"


# ============================================ 12. docs only from the host


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_docs_are_hidden_from_other_computers(client: TestClient, path: str) -> None:
    # TestClient's default address is "testclient": not this computer.
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_docs_work_on_the_host_itself(address: str) -> None:
    # No ``with``: that would run start-up against the development database.
    # The docs routes need no database, so start-up is not required here.
    local = TestClient(app, client=(address, 50000))
    assert local.get("/openapi.json").status_code == 200
    assert local.get("/docs").status_code == 200


def test_hiding_docs_does_not_affect_the_api(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


# ================================================ 14. seed command line


def test_the_seed_script_has_no_password_option() -> None:
    with pytest.raises(SystemExit):
        seed.main(["--password", "tangerine-ladder-77"])


def test_the_seed_script_rejects_a_weak_password_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("KAIROS_ADMIN_PASSWORD", "password123")
    with pytest.raises(SystemExit):
        seed.main(["--email", "admin@example.com"])
