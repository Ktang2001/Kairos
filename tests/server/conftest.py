"""Shared fixtures for the server test suite.

Every test that asks for ``client`` or ``db_session`` runs against a throwaway
SQLite file in a temporary directory, never the development database. With a
bare ``TestClient(app)``, ``get_db`` would resolve to the real
``server/db/kairos.db``.

Two families of fixtures live here, one from each branch that was merged:

* Kaleb's: ``db_session`` (a session on the throwaway database, with a server
  settings row), ``make_user`` (a user plus a ready session token, without the
  sign-up round trip) and the ``auth_headers(token)`` helper. Also autouse
  resets for the login/resend cooldowns, an isolated encryption key, and a stub
  that captures 2FA emails instead of sending them.
* Nick2's: ``session_factory``, ``register`` (signs up through the real
  ``/auth/signup``), ``user_headers``, ``make_account`` and the named cast used
  across the team tests -- Lena the lead, Max a member, Ada an admin, Olga an
  outsider -- plus a ``team`` led by Lena.

MERGE-CRITICAL (whole file): keep the ``get_db`` / ``get_session_factory``
overrides and ``configure_sqlite`` on the engine; without them tests write into
the real database and the concurrency tests lose the locking they check.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from server import crypto, email_sender
from server.db.session import configure_sqlite, get_db, get_session_factory, open_session
from server.main import app
from server.models import Base
from server.models.role import Role
from server.models.server_settings import ServerSettings
from server.models.user import User
from server.services import auth_service, session_service, verification_service
from shared.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_PROJECT_LEAD

#: A password long enough for sign-up's minimum length.
TEST_PASSWORD = "correct-horse-battery"


def auth_headers(token: str) -> dict[str, str]:
    """Build the bearer-token auth header for a request (see server/api/dependencies.py)."""
    return {"Authorization": f"Bearer {token}"}


# ------------------------------------------------------- autouse isolation


@pytest.fixture(autouse=True)
def _reset_login_cooldown() -> Iterator[None]:
    """auth_service's failed-login cooldown is in-memory and per-process, not
    per-test-database: without this, attempt counts leak between tests."""
    auth_service._failed_login_attempts.clear()
    yield
    auth_service._failed_login_attempts.clear()


@pytest.fixture(autouse=True)
def _reset_resend_cooldown() -> Iterator[None]:
    """verification_service's resend-code cooldown, reset for the same reason."""
    verification_service._last_sent_at.clear()
    yield
    verification_service._last_sent_at.clear()


@pytest.fixture(autouse=True)
def _isolated_encryption_key(tmp_path, monkeypatch) -> None:
    """Point server/crypto.py at a throwaway per-test key, never the real one."""
    monkeypatch.setattr(crypto, "DEFAULT_KEY_PATH", tmp_path / "test.key")


@pytest.fixture(autouse=True)
def sent_codes(monkeypatch) -> list[tuple[str, str]]:
    """Capture 2FA emails as (to_email, code) instead of connecting to SMTP."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        email_sender, "send_verification_code", lambda to_email, code: sent.append((to_email, code))
    )
    return sent


# ---------------------------------------------------- throwaway database


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A throwaway database built from the models, with the real server's
    SQLite settings (WAL, busy timeout, BEGIN IMMEDIATE for writes).

    A file, not ``:memory:``: an in-memory database is shared across
    connections in a way the real file is not, which hides real bugs.
    """
    test_engine = configure_sqlite(
        create_engine(
            f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
            connect_args={"check_same_thread": False},
        )
    )
    Base.metadata.create_all(test_engine)
    yield test_engine
    test_engine.dispose()


@pytest.fixture
def session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture
def seeded_roles(session_factory: sessionmaker[Session]) -> None:
    """Create the three role rows a running server would have."""
    db = session_factory()
    try:
        auth_service.ensure_roles(db)
    finally:
        db.close()


@pytest.fixture
def db_session(
    tmp_path: Path, engine: Engine, session_factory: sessionmaker[Session], seeded_roles: None
) -> Iterator[Session]:
    """A session on the throwaway database, with a server settings row, and the
    app's ``get_db`` / ``get_session_factory`` pointed at that database.

    The test's own session uses a plain connection (the sqlite3 driver's default
    of starting a transaction only at the first write), not the server's
    BEGIN-at-every-read settings: tests hold this session open across requests,
    and a read transaction left open while a request writes is refused when it
    later writes itself ("database is locked" in WAL mode). The requests still
    go through the server's real locking (``open_session`` below).
    """
    test_engine = create_engine(engine.url, connect_args={"check_same_thread": False})
    session = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)()
    session.add(
        ServerSettings(
            id=1,
            display_name="Test Server",
            upload_root=str(tmp_path / "uploads"),
            max_upload_size_bytes=10 * 1024 * 1024,
        )
    )
    session.commit()

    def override_get_db(request: Request = None) -> Iterator[Session]:  # type: ignore[assignment]
        # Same per-request locking as the real get_db (server.db.session).
        yield from open_session(session_factory, request)

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    try:
        yield session
    finally:
        session.close()
        test_engine.dispose()
        # Leaving overrides in place would leak this database into later tests.
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_session_factory, None)


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """A TestClient on the throwaway database (start-up runs against it too)."""
    with TestClient(app) as test_client:
        yield test_client


# ------------------------------------------------------------- Kaleb's


@pytest.fixture()
def make_user(db_session: Session):
    """Factory: a User (optionally with a given global role) plus a real login
    session -- ``user.token`` is what ``auth_headers()`` expects, standing in
    for the sign-up/login round trip most tests don't need to perform.
    """

    def _make_user(name: str, email: str, role_name: str = "member") -> User:
        role = db_session.query(Role).filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name)
            db_session.add(role)
            db_session.flush()
        user = User(name=name, email=email, password_hash="placeholder", role_id=role.id)
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        user.token = session_service.create_session(db_session, user.id).token
        return user

    return _make_user


# ------------------------------------------------------------- Nick2's


@pytest.fixture
def register(client: TestClient) -> Callable[..., dict]:
    """Sign up through the real ``POST /auth/signup`` and return its body
    (``{"id", "name", "email", "token"}``)."""

    def _register(
        name: str = "Test User",
        email: str = "user@example.com",
        password: str = TEST_PASSWORD,
    ) -> dict:
        response = client.post(
            "/auth/signup", json={"name": name, "email": email, "password": password}
        )
        assert response.status_code == 200, response.text
        return response.json()

    return _register


@pytest.fixture
def user_headers(register: Callable[..., dict]) -> Callable[..., dict[str, str]]:
    """Sign a new member up, then return an Authorization header for them."""

    def _user_headers(
        email: str = "member@example.com",
        password: str = TEST_PASSWORD,
        name: str = "Test User",
    ) -> dict[str, str]:
        body = register(name=name, email=email, password=password)
        return auth_headers(body["token"])

    return _user_headers


@dataclass
class Account:
    """A registered user as the team tests need them: who, and how to act as them."""

    id: int
    email: str
    headers: dict[str, str]


def set_role(session_factory: sessionmaker[Session], email: str, role_name: str) -> None:
    """Change a user's app-wide role directly in the database (holding the write
    lock from the start, as server writes do)."""
    db = session_factory(
        bind=session_factory.kw["bind"].execution_options(sqlite_begin_mode="IMMEDIATE")
    )
    try:
        user = auth_service.get_user_by_email(db, email)
        role = auth_service.get_role_by_name(db, role_name)
        assert user is not None and role is not None
        user.role_id = role.id
        db.commit()
    finally:
        db.close()


@pytest.fixture
def make_account(
    register: Callable[..., dict], session_factory: sessionmaker[Session]
) -> Callable[..., Account]:
    """Sign a user up with the given role and return their id, email and headers."""

    def _make(name: str, role: str = ROLE_MEMBER) -> Account:
        email = f"{name.lower()}@example.com"
        body = register(name=name, email=email)
        if role != ROLE_MEMBER:
            set_role(session_factory, email, role)
        return Account(id=body["id"], email=email, headers=auth_headers(body["token"]))

    return _make


@pytest.fixture
def lead(make_account: Callable[..., Account]) -> Account:
    return make_account("Lena", ROLE_PROJECT_LEAD)


@pytest.fixture
def admin(make_account: Callable[..., Account]) -> Account:
    return make_account("Ada", ROLE_ADMIN)


@pytest.fixture
def member(make_account: Callable[..., Account]) -> Account:
    return make_account("Max")


@pytest.fixture
def outsider(make_account: Callable[..., Account]) -> Account:
    return make_account("Olga")


@pytest.fixture
def team(client: TestClient, lead: Account, member: Account) -> dict:
    """A team led by ``lead`` with ``member`` on it. ``outsider`` is not on it."""
    response = client.post("/teams", json={"name": "Alpha"}, headers=lead.headers)
    assert response.status_code == 201, response.text
    team_id = response.json()["id"]

    response = client.post(
        f"/teams/{team_id}/members", json={"email": member.email}, headers=lead.headers
    )
    assert response.status_code == 201, response.text
    return response.json()
