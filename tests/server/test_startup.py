"""Tests for what has to be true before the server can serve its first request.

Covers the start-up role seeding in ``server.main.lifespan`` and the single
database location in ``server.db.config`` that both the app and alembic use.
"""

import os
import sqlite3
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from server.db import config as db_config
from server.db import session as db_session
from server.db.session import get_db, open_session
from server.main import app
from server.models.role import Role
from shared.roles import ALL_ROLES

REPO_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = REPO_ROOT / "server" / "db" / "alembic.ini"


def _override_with(factory: sessionmaker[Session]) -> None:
    def override_get_db(request: Request = None) -> Iterator[Session]:  # type: ignore[assignment]
        # Same per-request locking as the real get_db (server.db.session).
        yield from open_session(factory, request)

    app.dependency_overrides[get_db] = override_get_db


def _migrate(database_file: Path) -> None:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_file.as_posix()}")
    command.upgrade(cfg, "head")


def test_startup_creates_roles_on_an_empty_database(
    session_factory: sessionmaker[Session],
) -> None:
    """The ``engine`` fixture has tables but no role rows, like a fresh migration."""
    _override_with(session_factory)
    try:
        with TestClient(app):
            pass
    finally:
        app.dependency_overrides.clear()

    db = session_factory()
    try:
        names = set(db.scalars(select(Role.name)))
    finally:
        db.close()
    assert names == set(ALL_ROLES)


def test_register_works_on_a_freshly_migrated_database(tmp_path: Path) -> None:
    """The bug this guards: migrations leave roles empty, so registering gave a 500."""
    database_file = tmp_path / "fresh.db"
    _migrate(database_file)

    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    _override_with(sessionmaker(bind=engine, autoflush=False, autocommit=False))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/register",
                json={
                    "name": "New",
                    "email": "new@example.com",
                    "password": "correct-horse-battery",
                },
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert response.status_code == 201, response.text
    assert response.json()["user"]["role"] == "member"


def test_startup_is_idempotent(session_factory: sessionmaker[Session]) -> None:
    _override_with(session_factory)
    try:
        with TestClient(app):
            pass
        with TestClient(app):
            pass
    finally:
        app.dependency_overrides.clear()

    db = session_factory()
    try:
        assert len(list(db.scalars(select(Role)))) == len(ALL_ROLES)
    finally:
        db.close()


def test_startup_on_an_unmigrated_database_says_how_to_fix_it(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    _override_with(sessionmaker(bind=engine, autoflush=False, autocommit=False))
    try:
        with pytest.raises(RuntimeError, match="alembic"), TestClient(app):
            pass
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def test_app_engine_uses_the_configured_database() -> None:
    assert db_session.engine.url.database is not None
    assert Path(db_session.engine.url.database) == db_config.DB_PATH


def test_database_path_is_absolute() -> None:
    """A relative path would resolve against the CWD and silently pick a different file."""
    assert db_config.DB_PATH.is_absolute()


@pytest.mark.parametrize("cwd", ["repo-root", "server/db", "outside-repo"])
def test_alembic_runs_from_any_directory(tmp_path: Path, cwd: str) -> None:
    """Alembic used to fail with "unable to open database file" outside the repo root.

    Runs ``alembic current``, which has to open the configured database but
    only reads from it. Skipped when there is no development database, since
    opening a missing SQLite file would create an empty one.
    """
    if not db_config.DB_PATH.exists():
        pytest.skip("no development database to open")

    working_dir = {
        "repo-root": REPO_ROOT,
        "server/db": REPO_ROOT / "server" / "db",
        "outside-repo": tmp_path,
    }[cwd]

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "current"],
        cwd=working_dir,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
    )
    assert result.returncode == 0, result.stderr


def test_migrations_upgrade_downgrade_upgrade(tmp_path: Path) -> None:
    database_file = tmp_path / "roundtrip.db"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_file.as_posix()}")

    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")

    conn = sqlite3.connect(database_file)
    try:
        names = {row[0] for row in conn.execute("select name from sqlite_master")}
    finally:
        conn.close()
    assert {"users", "roles", "sessions", "messages", "teams", "tasks"} <= names
    # Autogenerate cannot see this expression index on SQLite, so it was added
    # to the migration by hand; make sure it really is there.
    assert "uq_teams_name_lower" in names
