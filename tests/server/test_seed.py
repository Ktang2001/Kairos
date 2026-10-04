"""Tests for ``python -m server.seed``, which creates the first admin account.

``seed()`` opens ``SessionLocal`` itself, so each test points that at the
throwaway database from conftest -- never the development ``kairos.db``. The
``engine`` fixture builds the tables but no role rows, like a freshly
migrated database, so creating the roles is exercised too.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server import seed
from server.db.session import configure_sqlite
from server.services import auth_service
from server.services.password_service import verify_password
from shared.roles import ROLE_ADMIN, ROLE_DISPLAY_NAMES, ROLE_MEMBER

ADMIN_EMAIL = "boss@example.com"
ADMIN_PASSWORD = "tangerine-ladder-cobalt"


@pytest.fixture
def db_factory(
    session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> sessionmaker[Session]:
    monkeypatch.setattr(seed, "SessionLocal", session_factory)
    monkeypatch.delenv("KAIROS_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("KAIROS_ADMIN_EMAIL", raising=False)
    monkeypatch.delenv("KAIROS_ADMIN_NAME", raising=False)
    return session_factory


@pytest.fixture
def chosen_password(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("KAIROS_ADMIN_PASSWORD", ADMIN_PASSWORD)
    return ADMIN_PASSWORD


def _user(factory: sessionmaker[Session], email: str = ADMIN_EMAIL):
    db = factory()
    try:
        user = auth_service.get_user_by_email(db, email)
        return None if user is None else (user.name, user.role.name, user.password_hash)
    finally:
        db.close()


def _generated_password(output: str) -> str | None:
    for line in output.splitlines():
        if "generated admin password:" in line:
            return line.split(":", 1)[1].strip()
    return None


# ------------------------------------------------------------ creating


def test_creates_the_roles_and_an_admin(
    db_factory: sessionmaker[Session], chosen_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed.main(["--email", ADMIN_EMAIL, "--name", "Boss"]) == 0

    out = capsys.readouterr().out
    assert "created admin: boss@example.com" in out
    assert all(role in out for role in ROLE_DISPLAY_NAMES)
    name, role, password_hash = _user(db_factory)
    assert (name, role) == ("Boss", ROLE_ADMIN)
    assert verify_password(chosen_password, password_hash)


def test_a_chosen_password_is_never_printed(
    db_factory: sessionmaker[Session], chosen_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    seed.main(["--email", ADMIN_EMAIL])
    out = capsys.readouterr().out
    assert chosen_password not in out
    assert _generated_password(out) is None


def test_without_a_chosen_password_one_is_generated_and_shown_once(
    db_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed.main(["--email", ADMIN_EMAIL]) == 0

    printed = _generated_password(capsys.readouterr().out)
    assert printed is not None and len(printed) >= 20
    assert verify_password(printed, _user(db_factory)[2])


def test_the_defaults_come_from_the_environment(
    db_factory: sessionmaker[Session], chosen_password: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAIROS_ADMIN_EMAIL", "env@example.com")
    monkeypatch.setenv("KAIROS_ADMIN_NAME", "Env Admin")
    assert seed.main([]) == 0
    assert _user(db_factory, "env@example.com")[:2] == ("Env Admin", ROLE_ADMIN)


# ------------------------------------------------------------ running again


def test_running_twice_keeps_the_first_admin(
    db_factory: sessionmaker[Session], chosen_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    seed.main(["--email", ADMIN_EMAIL])
    first_hash = _user(db_factory)[2]
    capsys.readouterr()

    assert seed.main(["--email", ADMIN_EMAIL]) == 0
    assert "admin already exists: boss@example.com" in capsys.readouterr().out
    assert _user(db_factory)[2] == first_hash


def test_a_second_run_does_not_print_a_password_that_was_never_saved(
    db_factory: sessionmaker[Session], capsys: pytest.CaptureFixture[str]
) -> None:
    seed.main(["--email", ADMIN_EMAIL])
    capsys.readouterr()

    assert seed.main(["--email", ADMIN_EMAIL]) == 0
    # Writing this down would lock the admin out: it is not their password.
    assert _generated_password(capsys.readouterr().out) is None


def test_an_existing_non_admin_account_is_reported_not_promoted(
    db_factory: sessionmaker[Session], chosen_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    # Someone signed up with the admin address before the seed ran.
    db = db_factory()
    try:
        auth_service.ensure_roles(db)
        auth_service.register_user(
            db, name="Early Bird", email=ADMIN_EMAIL, password="pelican-harbor-lantern"
        )
    finally:
        db.close()

    assert seed.main(["--email", ADMIN_EMAIL]) == 1

    captured = capsys.readouterr()
    assert "not an admin" in captured.err
    assert "already exists" not in captured.out
    assert _user(db_factory)[1] == ROLE_MEMBER  # handing them admin would be a takeover


# ------------------------------------------------------------ refusing


def test_a_short_password_is_refused(
    db_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAIROS_ADMIN_PASSWORD", "short")
    with pytest.raises(SystemExit) as exit_info:
        seed.main(["--email", ADMIN_EMAIL])
    assert exit_info.value.code == 2
    assert _user(db_factory) is None


@pytest.fixture
def unmigrated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """A database file with no tables: ``alembic upgrade head`` was never run."""
    engine = configure_sqlite(create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"))
    monkeypatch.setattr(seed, "SessionLocal", sessionmaker(bind=engine))
    yield
    engine.dispose()


def test_an_unmigrated_database_gets_advice_not_a_traceback(
    unmigrated: None, chosen_password: str, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seed.main(["--email", ADMIN_EMAIL]) == 1
    assert "alembic -c server/db/alembic.ini upgrade head" in capsys.readouterr().err


def test_a_refused_account_is_reported_not_a_traceback(
    db_factory: sessionmaker[Session],
    chosen_password: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def refused(*_args, **_kwargs):
        raise auth_service.EmailAlreadyRegistered(ADMIN_EMAIL)  # e.g. lost a race

    monkeypatch.setattr(auth_service, "register_user", refused)
    assert seed.main(["--email", ADMIN_EMAIL]) == 1
    assert "could not create the admin account" in capsys.readouterr().err
