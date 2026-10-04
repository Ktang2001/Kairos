"""Shared test fixtures for server tests that need an isolated database.

The pre-existing tests (test_health.py, test_messages.py) talk to the real
server/db/kairos.db via a module-level TestClient and are untouched by this file.
Any new test that needs its own clean database (conversations, chat, attachments)
should request the `client`/`db_session`/`make_user` fixtures below instead, which
point the app at a throwaway SQLite file for the duration of the test.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server.db.session import get_db, get_session_factory
from server.main import app
from server.models import Base
from server.models.role import Role
from server.models.server_settings import ServerSettings
from server.models.user import User

PLACEHOLDER_USER_HEADER = "X-Kairos-User-Id"


def auth_headers(user_id: int) -> dict[str, str]:
    """Build the placeholder current-user header for a request (see server/api/dependencies.py)."""
    return {PLACEHOLDER_USER_HEADER: str(user_id)}


@pytest.fixture()
def db_session(tmp_path) -> Iterator[Session]:
    db_path = tmp_path / "test.db"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(engine)

    session = testing_session_local()
    session.add(
        ServerSettings(
            id=1,
            display_name="Test Server",
            upload_root=str(tmp_path / "uploads"),
            max_upload_size_bytes=10 * 1024 * 1024,
        )
    )
    session.commit()

    def override_get_db() -> Iterator[Session]:
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_session_factory] = lambda: testing_session_local
    try:
        yield session
    finally:
        session.close()
        app.dependency_overrides.pop(get_db, None)
        app.dependency_overrides.pop(get_session_factory, None)
        engine.dispose()


@pytest.fixture()
def client(db_session: Session) -> TestClient:
    return TestClient(app)


@pytest.fixture()
def make_user(db_session: Session):
    """Factory fixture: create a User (optionally with a given global Role) for a test."""

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
        return user

    return _make_user
