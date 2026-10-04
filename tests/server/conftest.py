"""Shared fixtures for the server test suite.

Every test runs against a throwaway SQLite file in a temporary directory, never
the development database. That override is the whole point of this file: with a
bare ``TestClient(app)``, the ``get_db`` dependency resolves to the real
``server/db/kairos.db``, so merely running the suite would write rows into the
database a teammate is using, and assertions such as "this is the only user"
would depend on whatever previous runs happened to leave behind.

Fixtures here, from the bottom up: ``engine`` (a temporary database file built
from the models) -> ``session_factory`` -> ``seeded_roles`` (the three roles)
-> ``client`` (a TestClient wired to that database) -> helpers that register
people (``register``, ``make_account``) and the named cast used across the
team tests: Lena the lead, Max a member, Ada an admin, Olga an outsider.

MERGE-CRITICAL (whole file): when merging another branch's fixtures, add
them here and keep these. Above all keep the ``get_db`` override in
``client`` and ``configure_sqlite`` in ``engine``: without them the tests
write into the real server/db/kairos.db and the concurrency tests lose the
locking they check.
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

from server.db.session import configure_sqlite, get_db, open_session
from server.main import app
from server.models import Base
from server.services import auth_service
from shared.roles import ROLE_ADMIN, ROLE_MEMBER, ROLE_PROJECT_LEAD

#: A password long enough to satisfy RegisterRequest's minimum length.
TEST_PASSWORD = "correct-horse-battery"


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    """A throwaway database whose schema is built from the models.

    A file inside ``tmp_path`` rather than ``sqlite:///:memory:`` on purpose: an
    in-memory database is shared across connections in a way the real file-based
    database is not, which hides exactly the kind of bug (a second connection
    seeing no tables) that this suite exists to catch.
    """
    database_file = tmp_path / "test.db"
    test_engine = configure_sqlite(
        create_engine(
            f"sqlite:///{database_file.as_posix()}",
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
    """Create the role rows a migrated database would already have."""
    db = session_factory()
    try:
        auth_service.ensure_roles(db)
    finally:
        db.close()


@pytest.fixture
def client(
    session_factory: sessionmaker[Session],
    seeded_roles: None,
) -> Iterator[TestClient]:
    """A TestClient whose database dependency points at the throwaway database."""

    def override_get_db(request: Request = None) -> Iterator[Session]:  # type: ignore[assignment]
        # Same per-request locking as the real get_db (server.db.session).
        yield from open_session(session_factory, request)

    app.dependency_overrides[get_db] = override_get_db
    # The login lockout lives on the shared app object; without a reset, wrong
    # passwords from one test would lock the same email in a later test.
    app.state.login_throttle.reset()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        # Leaving overrides in place would leak the temp database into whatever
        # test runs next, including the ones that use the real app object.
        app.dependency_overrides.clear()


@pytest.fixture
def register(client: TestClient) -> Callable[..., dict]:
    """Register a user and return the decoded response body.

    Returns the body rather than the whole response because almost every caller
    wants the token, and asserting the status here keeps that out of each test.
    """

    def _register(
        name: str = "Test User",
        email: str = "user@example.com",
        password: str = TEST_PASSWORD,
    ) -> dict:
        response = client.post(
            "/auth/register",
            json={"name": name, "email": email, "password": password},
        )
        assert response.status_code == 201, response.text
        return response.json()

    return _register


@pytest.fixture
def auth_headers(register: Callable[..., dict]) -> Callable[..., dict[str, str]]:
    """Register a user, then return an Authorization header for their token."""

    def _auth_headers(
        email: str = "member@example.com",
        password: str = TEST_PASSWORD,
        name: str = "Test User",
    ) -> dict[str, str]:
        body = register(name=name, email=email, password=password)
        return {"Authorization": f"Bearer {body['token']}"}

    return _auth_headers


# ------------------------------------------------- named accounts and a team
#
# Lena leads team "Alpha", Max is a plain member of it, Ada is an admin who is
# not on it, and Olga is a plain user who is not on it.


@dataclass
class Account:
    """A registered user as the tests need them: who they are and how to act as them."""

    id: int
    email: str
    headers: dict[str, str]


def set_role(session_factory: sessionmaker[Session], email: str, role_name: str) -> None:
    """Change a user's app-wide role directly in the database."""
    db = session_factory()
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
    client: TestClient, session_factory: sessionmaker[Session]
) -> Callable[..., Account]:
    """Register a user with the given role and return their id, email and headers."""

    def _make(name: str, role: str = ROLE_MEMBER) -> Account:
        email = f"{name.lower()}@example.com"
        response = client.post(
            "/auth/register",
            json={"name": name, "email": email, "password": TEST_PASSWORD},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        if role != ROLE_MEMBER:
            set_role(session_factory, email, role)
        return Account(
            id=body["user"]["id"],
            email=email,
            headers={"Authorization": f"Bearer {body['token']}"},
        )

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
