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


def test_signup_works_on_a_freshly_migrated_database(tmp_path: Path) -> None:
    """The bug this guards: migrations leave roles empty, so signing up gave a 500."""
    database_file = tmp_path / "fresh.db"
    _migrate(database_file)

    engine = create_engine(f"sqlite:///{database_file.as_posix()}")
    _override_with(sessionmaker(bind=engine, autoflush=False, autocommit=False))
    try:
        with TestClient(app) as client:
            response = client.post(
                "/auth/signup",
                json={
                    "name": "New",
                    "email": "new@example.com",
                    "password": "correct-horse-battery",
                },
            )
            assert response.status_code == 200, response.text
            me = client.get(
                "/people/me", headers={"Authorization": f"Bearer {response.json()['token']}"}
            )
    finally:
        app.dependency_overrides.clear()
        engine.dispose()

    assert me.json()["role"] == "member"


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


def test_existing_deadlines_get_end_of_day_when_upgraded(tmp_path: Path) -> None:
    """Migration e36d129f7870 gives every existing deadline an exact time: 11:59 PM
    on its date in this computer's zone (stored as UTC)."""
    from datetime import UTC, date, datetime, time

    database_file = tmp_path / "deadlines.db"
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{database_file.as_posix()}")
    command.upgrade(cfg, "bd9be5aae993")
    conn = sqlite3.connect(database_file)
    try:
        conn.execute("insert into roles (id, name) values (1, 'member')")
        conn.execute(
            "insert into users (id, name, email, password_hash, role_id) "
            "values (1, 'Max', 'max@example.com', 'x', 1)"
        )
        conn.execute("insert into teams (id, name, lead_id) values (1, 'Alpha', 1)")
        conn.execute(
            "insert into projects (id, team_id, name, status) values (1, 1, 'Site', 'active')"
        )
        conn.execute(
            "insert into tasks (id, project_id, title, status, due_date) "
            "values (1, 1, 'Dated', 'todo', '2026-11-04')"
        )
        conn.execute(
            "insert into tasks (id, project_id, title, status) values (2, 1, 'Undated', 'todo')"
        )
        conn.execute(
            "insert into subtasks (id, task_id, title, status, due_date) "
            "values (1, 1, 'Sub', 'todo', '2026-11-05')"
        )
        conn.commit()
    finally:
        conn.close()

    command.upgrade(cfg, "head")

    conn = sqlite3.connect(database_file)
    try:
        tasks = dict(conn.execute("select id, due_at from tasks").fetchall())
        subtask_due = conn.execute("select due_at from subtasks").fetchone()[0]
    finally:
        conn.close()

    def end_of_day(day: date) -> datetime:
        return datetime.combine(day, time(23, 59)).astimezone().astimezone(UTC).replace(tzinfo=None)

    assert datetime.fromisoformat(tasks[1]) == end_of_day(date(2026, 11, 4))
    assert tasks[2] is None
    assert datetime.fromisoformat(subtask_due) == end_of_day(date(2026, 11, 5))
    command.downgrade(cfg, "bd9be5aae993")


# ------------------------------------------- database version (found in use)


def _versioned_engine(tmp_path, revision: str):
    """A database built from the models but stamped with ``revision``."""
    from sqlalchemy import create_engine

    from server.models import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'v.db').as_posix()}")
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.exec_driver_sql("create table alembic_version (version_num varchar(32) primary key)")
        c.exec_driver_sql(f"insert into alembic_version values ('{revision}')")
    return engine


def test_an_upgraded_database_passes_the_check(tmp_path) -> None:
    from server.db.schema_check import code_head, database_problem

    assert database_problem(_versioned_engine(tmp_path, code_head())) is None


def test_an_old_database_is_refused_with_the_command_to_fix_it(tmp_path) -> None:
    """Found in use: an un-upgraded database made the Projects tab answer 500."""
    from server.db.schema_check import UPGRADE_COMMAND, database_problem

    problem = database_problem(_versioned_engine(tmp_path, "b3dc54a36214"))
    assert problem is not None
    assert UPGRADE_COMMAND in problem
    assert "b3dc54a36214" in problem


def test_a_database_newer_than_the_code_is_explained(tmp_path) -> None:
    from server.db.schema_check import database_problem

    problem = database_problem(_versioned_engine(tmp_path, "ffffffffffff"))
    assert problem is not None and "newer than this copy" in problem


def test_a_database_without_a_version_record_is_not_checked(tmp_path) -> None:
    from sqlalchemy import create_engine

    from server.db.schema_check import database_problem
    from server.models import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'plain.db').as_posix()}")
    Base.metadata.create_all(engine)
    assert database_problem(engine) is None


def test_the_server_refuses_to_start_on_an_old_database(tmp_path) -> None:
    import pytest
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from server.db.session import get_db
    from server.main import create_app

    engine = _versioned_engine(tmp_path, "b3dc54a36214")
    factory = sessionmaker(bind=engine)

    def override():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override
    with pytest.raises(RuntimeError, match="needs upgrading"), TestClient(app):
        pass
