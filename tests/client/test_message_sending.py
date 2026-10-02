"""Regression tests for "one message gets sent twice".

Every message was posted twice, 1-2 seconds apart. Two causes combined:

1. On Windows "localhost" resolves to IPv6 ::1 first; the server listens on
   IPv4 only, so each request waited ~2 s before falling back to 127.0.0.1.
2. During that wait the text stayed in an unlocked box with no sign anything
   was happening, so pressing Enter again sent it again.

``GatedClient`` stands in for the network: ``send_message`` blocks until the
test releases it, reproducing a slow send on demand.
"""

import threading
import time

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient, ApiError, normalise_base_url
from client.api_client.client import DEFAULT_BASE_URL
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import Session
from client.views.home_view import HomeView

WAIT_MS = 5000


class GatedClient:
    def __init__(self, fail_with: str | None = None) -> None:
        self.base_url = "http://127.0.0.1:9"
        self.token = "t"
        self.sent: list[str] = []
        self._gate = threading.Event()
        self._fail_with = fail_with

    def release(self) -> None:
        self._gate.set()

    def send_message(self, content: str) -> dict:
        self.sent.append(content)
        self._gate.wait(5)
        if self._fail_with:
            raise ApiError(self._fail_with)
        return {"id": len(self.sent), "sender": "Nick", "content": content}

    def logout(self) -> None:
        self.token = None


def _home(qtbot: QtBot, client: GatedClient) -> HomeView:
    session = Session(
        client=client, user={"id": 1, "name": "Nick", "email": "n@x.co", "role": "member"}
    )
    view = HomeView(HomeViewModel(session, runner=BackgroundRunner()))
    qtbot.addWidget(view)
    view.show()
    return view


@pytest.fixture
def slow() -> GatedClient:
    client = GatedClient()
    yield client
    client.release()


# ------------------------------------------------------- one send per message


def test_pressing_enter_twice_during_a_slow_send_sends_once(
    qtbot: QtBot, slow: GatedClient
) -> None:
    view = _home(qtbot, slow)
    view.message_input.setText("hello")
    qtbot.keyClick(view.message_input, Qt.Key.Key_Return)
    qtbot.keyClick(view.message_input, Qt.Key.Key_Return)
    qtbot.mouseClick(view.send_button, Qt.MouseButton.LeftButton)
    view._send()  # even a direct second call

    with qtbot.waitSignal(view.viewmodel.message_sent, timeout=WAIT_MS):
        slow.release()
    qtbot.wait(100)
    assert slow.sent == ["hello"]
    assert view.log.toPlainText() == "You: hello"


def test_the_box_is_cleared_and_locked_while_sending(qtbot: QtBot, slow: GatedClient) -> None:
    view = _home(qtbot, slow)
    view.message_input.setText("hello")
    view._send()

    assert view.message_input.text() == ""
    assert not view.message_input.isEnabled()
    assert not view.send_button.isEnabled()
    assert view.send_button.text() == "Sending…"

    with qtbot.waitSignal(view.viewmodel.message_sent, timeout=WAIT_MS):
        slow.release()
    assert view.message_input.isEnabled()
    assert view.send_button.isEnabled()
    assert view.send_button.text() == "Send"


def test_the_next_message_can_be_sent_after_the_first_arrives(qtbot: QtBot) -> None:
    client = GatedClient()
    client.release()  # no delay
    view = _home(qtbot, client)
    for text in ("one", "two", "three"):
        view.message_input.setText(text)
        with qtbot.waitSignal(view.viewmodel.message_sent, timeout=WAIT_MS):
            view._send()
    assert client.sent == ["one", "two", "three"]
    assert view.log.toPlainText().splitlines() == ["You: one", "You: two", "You: three"]


def test_a_blank_message_is_not_sent_and_does_not_lock_the_box(
    qtbot: QtBot, slow: GatedClient
) -> None:
    view = _home(qtbot, slow)
    view.message_input.setText("   ")
    view._send()
    qtbot.wait(50)
    assert slow.sent == []
    assert view.message_input.isEnabled()


# --------------------------------------------------------------- failures


def test_a_failed_send_gives_the_text_back(qtbot: QtBot) -> None:
    client = GatedClient(fail_with="Can't reach the server")
    client.release()
    view = _home(qtbot, client)
    view.message_input.setText("important note")

    with qtbot.waitSignal(view.viewmodel.send_failed, timeout=WAIT_MS):
        view._send()

    assert view.message_input.text() == "important note"
    assert view.message_input.isEnabled()
    assert view.error_label.text() == "Send failed: Can't reach the server"
    assert view.log.toPlainText() == ""


def test_text_typed_during_a_failed_send_is_not_overwritten(qtbot: QtBot) -> None:
    client = GatedClient(fail_with="nope")
    view = _home(qtbot, client)
    view.message_input.setText("first")
    view._send()
    # (The box is locked while sending; simulate text arriving another way.)
    view.message_input.setText("something newer")
    with qtbot.waitSignal(view.viewmodel.send_failed, timeout=WAIT_MS):
        client.release()
    assert view.message_input.text() == "something newer"


def test_signing_out_while_sending_leaves_the_box_locked(qtbot: QtBot, slow: GatedClient) -> None:
    view = _home(qtbot, slow)
    view.message_input.setText("bye")
    view._send()
    qtbot.mouseClick(view.sign_out_button, Qt.MouseButton.LeftButton)
    with qtbot.waitSignal(view.viewmodel.signed_out, timeout=WAIT_MS):
        slow.release()
    assert not view.send_button.isEnabled()
    assert not view.message_input.isEnabled()


# ------------------------------------------------------ localhost is slow


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("localhost:8000", "http://127.0.0.1:8000"),
        ("http://localhost:8000/", "http://127.0.0.1:8000"),
        ("LOCALHOST:8000", "http://127.0.0.1:8000"),
        ("https://localhost", "https://127.0.0.1"),
        ("localhost.example.com:8000", "http://localhost.example.com:8000"),
        ("mylocalhost:8000", "http://mylocalhost:8000"),
    ],
)
def test_localhost_is_rewritten_to_ipv4(typed: str, expected: str) -> None:
    assert normalise_base_url(typed) == expected


def test_the_default_address_avoids_localhost() -> None:
    assert "localhost" not in DEFAULT_BASE_URL
    assert normalise_base_url(DEFAULT_BASE_URL) == "http://127.0.0.1:8000"


def test_requests_to_the_local_server_are_fast(live_server: str) -> None:
    """The real symptom: ~2 s per request via "localhost" on Windows."""
    port = live_server.rsplit(":", 1)[1]
    client = ApiClient(f"localhost:{port}")
    start = time.perf_counter()
    for _ in range(3):
        client.health()
    assert (time.perf_counter() - start) / 3 < 0.5


def test_the_viewmodel_itself_refuses_a_second_send(qtbot: QtBot, slow: GatedClient) -> None:
    """Defence in depth: even without the screen's lock (another caller, a
    future screen), the view model sends one message at a time.
    """
    session = Session(
        client=slow, user={"id": 1, "name": "Nick", "email": "n@x.co", "role": "member"}
    )
    viewmodel = HomeViewModel(session, runner=BackgroundRunner())
    viewmodel.send_message("hello")
    viewmodel.send_message("hello")
    assert viewmodel.sending
    with qtbot.waitSignal(viewmodel.message_sent, timeout=WAIT_MS):
        slow.release()
    qtbot.wait(100)
    assert slow.sent == ["hello"]
