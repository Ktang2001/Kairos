"""Shared fixtures for the Qt client tests.

``live_server`` runs the real FastAPI app under uvicorn on a throwaway SQLite
file, so these tests exercise the client against the actual API over real
HTTP. It uses its own ``create_app()`` instance: the server tests set and
clear ``dependency_overrides`` on the module-level ``app``, and sharing it
would let them pull the database out from under this server mid-run.

Also here: ``dead_server`` / ``silent_server`` (a host that is off / hung),
``settings`` (remembered values in a temp file, never the real ones), and an
automatic fixture that runs around every client test (see below).

MERGE-CRITICAL (whole file): when merging another branch's fixtures (e.g. a
stub discovery listener), add them here and keep these -- in particular the
automatic ``background_work_stays_inside_its_test`` fixture. Without it, a
request from one test lands in the next, and the suite crashes now and then.
"""

import gc
import itertools
import os
import socket
import threading
import time
from collections.abc import Iterator
from pathlib import Path

# Must be set before any QApplication exists: lets the suite run with no
# display (CI, or a Linux box over SSH) and keeps windows from popping up.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
import uvicorn
from fastapi import Request
from PySide6.QtCore import QCoreApplication, QEvent, QSettings
from PySide6.QtWidgets import QApplication
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from client.main_thread_gc import MainThreadGarbageCollector
from client.settings import ClientSettings
from client.viewmodels.background import wait_until_idle
from server.db.session import configure_sqlite, get_db, open_session
from server.main import create_app
from server.models import Base

TEST_PASSWORD = "correct-horse-battery"

#: For requests that only set up a test (registering people, etc.). Not the
#: app's 5 s limit: on a loaded machine password hashing alone can take
#: longer, and a slow setup step is not what these tests are checking.
SETUP_TIMEOUT = 30.0

#: The live server's session factory, so tests can set roles directly.
_LIVE_DB: dict = {}

_email_counter = itertools.count()


def unique_email(prefix: str = "user") -> str:
    """Every test registers its own account, since the live server is shared."""
    return f"{prefix}{next(_email_counter)}-{os.getpid()}@example.com"


def free_port() -> int:
    """A port nothing is listening on (bind to 0, read it back, release it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


@pytest.fixture(scope="session")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    database_file: Path = tmp_path_factory.mktemp("live") / "client-tests.db"
    engine = configure_sqlite(
        create_engine(
            f"sqlite:///{database_file.as_posix()}", connect_args={"check_same_thread": False}
        )
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    _LIVE_DB["factory"] = factory

    def override_get_db(request: Request = None) -> Iterator[Session]:  # type: ignore[assignment]
        # Same per-request locking as the real get_db (server.db.session).
        yield from open_session(factory, request)

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("live test server did not start")
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"

    server.should_exit = True
    thread.join(timeout=5)
    engine.dispose()


@pytest.fixture
def dead_server() -> str:
    """An address where nothing is listening: the "host is off" case."""
    return f"http://127.0.0.1:{free_port()}"


@pytest.fixture
def silent_server() -> Iterator[str]:
    """Accepts connections but never answers: the "host is hung" case."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}"
    finally:
        listener.close()


@pytest.fixture(autouse=True)
def background_work_stays_inside_its_test(qapp: QApplication) -> Iterator[None]:
    """Run each test the way the app runs, and leave nothing behind.

    * Garbage is collected on the main thread only, as in the app (see
      client/main_thread_gc.py). Otherwise the live server's thread or a
      request thread could collect a Qt object an earlier test left behind,
      and crash.
    * Afterwards, wait for every background request to finish, so none
      delivers its result in the middle of the next test, and collect what
      the test left behind -- here, on the main thread.
    """
    collector = MainThreadGarbageCollector()
    yield
    wait_until_idle(10.0)  # also delivers the finished requests' results
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    gc.collect()
    collector.stop()


@pytest.fixture
def settings(tmp_path: Path) -> ClientSettings:
    """Settings in a temp INI file, never the real per-user store."""
    return ClientSettings(QSettings(str(tmp_path / "kairos.ini"), QSettings.Format.IniFormat))


def set_live_role(email: str, role: str) -> None:
    """Change an account's role in the live server's database, the way an
    admin (or the seed script) would.
    """
    from server.services import auth_service

    db = _LIVE_DB["factory"]()
    try:
        user = auth_service.get_user_by_email(db, email)
        user.role_id = auth_service.get_role_by_name(db, role).id
        db.commit()
    finally:
        db.close()
