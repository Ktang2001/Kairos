"""Tests for the host's server window (server/gui.py).

Guards the bug where, on Windows, the window chose a port another program was
already using, failed to start, and still said "Server running".
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from server import gui
from server.db.session import get_db
from server.main import create_app
from server.models import Base

WAIT_MS = 15_000


@pytest.fixture
def busy_port() -> Iterator[int]:
    """A port another program is listening on, bound the way a real server
    would be (all interfaces, no SO_REUSEADDR).
    """
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("0.0.0.0", 0))
    listener.listen(5)
    try:
        yield listener.getsockname()[1]
    finally:
        listener.close()


@pytest.fixture
def server_window(
    qtbot: QtBot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[gui.ServerWindow]:
    """A server window wired to a throwaway database instead of the dev one."""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'gui.db').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(gui, "app", app)
    monkeypatch.setattr(gui, "SessionLocal", factory)

    window = gui.ServerWindow()
    qtbot.addWidget(window)
    yield window
    window._stop_server()
    engine.dispose()


def test_a_port_in_use_is_skipped(busy_port: int) -> None:
    assert gui.find_free_port("0.0.0.0", busy_port) != busy_port


def test_a_free_port_is_returned_as_is() -> None:
    with socket.socket() as probe:
        probe.bind(("0.0.0.0", 0))
        port = probe.getsockname()[1]
    assert gui.find_free_port("0.0.0.0", port) == port


def test_the_window_starts_on_the_next_port_when_the_first_is_taken(
    qtbot: QtBot,
    server_window: gui.ServerWindow,
    busy_port: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gui, "PORT", busy_port)

    server_window._on_toggle_clicked()

    qtbot.waitUntil(lambda: "Server running" in server_window.status_label.text(), timeout=WAIT_MS)
    assert server_window._port != busy_port
    assert f"port {busy_port} was taken" in server_window.status_label.text()
    assert server_window.toggle_button.text() == "Stop Server"


def test_a_failed_start_is_reported_not_shown_as_running(
    qtbot: QtBot,
    server_window: gui.ServerWindow,
    busy_port: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if the port check is fooled (or another program grabs the port in
    the moment between checking and starting), the window must not claim the
    server is running.
    """
    monkeypatch.setattr(gui, "find_free_port", lambda host, port: busy_port)
    server_window._on_toggle_clicked()

    qtbot.waitUntil(lambda: "Could not start" in server_window.status_label.text(), timeout=WAIT_MS)
    assert "Server running" not in server_window.status_label.text()
    assert str(busy_port) in server_window.status_label.text()
    assert server_window.toggle_button.text() == "Start Server"
    assert server_window.toggle_button.isEnabled()
    assert server_window._uvicorn_server is None


def test_the_window_says_starting_until_the_server_is_listening(
    server_window: gui.ServerWindow,
) -> None:
    server_window._on_toggle_clicked()
    assert "Starting server" in server_window.status_label.text()
    assert not server_window.toggle_button.isEnabled()


def test_start_then_stop(qtbot: QtBot, server_window: gui.ServerWindow) -> None:
    server_window._on_toggle_clicked()
    qtbot.waitUntil(lambda: "Server running" in server_window.status_label.text(), timeout=WAIT_MS)
    server_window._on_toggle_clicked()
    assert server_window.status_label.text() == "Server stopped"
    assert server_window.toggle_button.text() == "Start Server"


def test_the_address_line_wraps_and_can_be_copied(
    qtbot: QtBot, server_window: gui.ServerWindow
) -> None:
    """The client address is at the end of a long line; it must never be cut off."""
    server_window.resize(360, 300)
    server_window.show()
    server_window._on_toggle_clicked()
    qtbot.waitUntil(lambda: "Server running" in server_window.status_label.text(), timeout=WAIT_MS)

    label = server_window.status_label
    assert label.wordWrap()
    assert label.textInteractionFlags() & gui.Qt.TextInteractionFlag.TextSelectableByMouse
    assert label.width() <= server_window.width()


def test_the_server_does_not_trust_forwarded_headers(
    qtbot: QtBot, server_window: gui.ServerWindow
) -> None:
    """There is no proxy in front of Kairos, so X-Forwarded-For is always forged;
    trusting it let a caller choose their own address and dodge the login lockout.
    """
    server_window._on_toggle_clicked()
    qtbot.waitUntil(lambda: "Server running" in server_window.status_label.text(), timeout=WAIT_MS)
    assert server_window._uvicorn_server.config.proxy_headers is False
