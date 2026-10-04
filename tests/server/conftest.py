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

from server import crypto, email_sender
from server.db.session import get_db, get_session_factory
from server.main import app
from server.models import Base
from server.models.role import Role
from server.models.server_settings import ServerSettings
from server.models.user import User
from server.services import auth_service, session_service, verification_service


def auth_headers(token: str) -> dict[str, str]:
    """Build the bearer-token auth header for a request (see server/api/dependencies.py)."""
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _reset_login_cooldown() -> Iterator[None]:
    """auth_service's failed-login cooldown is deliberately in-memory/per-process
    (see server/services/auth_service.py), not per-test-database - without this it
    would leak attempt counts between tests that reuse the same email."""
    auth_service._failed_login_attempts.clear()
    yield
    auth_service._failed_login_attempts.clear()


@pytest.fixture(autouse=True)
def _reset_resend_cooldown() -> Iterator[None]:
    """verification_service's resend-code cooldown is the same in-memory/
    per-process idiom as auth_service's login cooldown above - reset it for the
    same reason."""
    verification_service._last_sent_at.clear()
    yield
    verification_service._last_sent_at.clear()


@pytest.fixture(autouse=True)
def _isolated_encryption_key(tmp_path, monkeypatch) -> None:
    """server/crypto.py's DEFAULT_KEY_PATH is a fixed real-machine path by design
    (see server/gui.py's CERT_PATH/KEY_PATH for the same pattern) - point it at a
    throwaway per-test file so tests never read/write the real dev key, and each
    test's "is this actually encrypted" checks aren't cross-contaminated."""
    monkeypatch.setattr(crypto, "DEFAULT_KEY_PATH", tmp_path / "test.key")


@pytest.fixture(autouse=True)
def sent_codes(monkeypatch) -> list[tuple[str, str]]:
    """Stubs server/email_sender.send_verification_code so tests never attempt a
    real SMTP connection - each call appends (to_email, code) here instead, so a
    test can grab the actual code that "would have" been emailed."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(
        email_sender, "send_verification_code", lambda to_email, code: sent.append((to_email, code))
    )
    return sent


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
    """Factory fixture: create a User (optionally with a given global Role) for a
    test, plus a real login session - `user.token` is what `auth_headers()` expects,
    standing in for the sign-up/login round trip most tests don't need to perform.
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
