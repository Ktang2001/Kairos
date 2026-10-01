"""Tests for the login and home screens, driven like a user would (pytest-qt).

Most run against the real API (``live_server``). The few that need control
over timing -- "the button is disabled while waiting", "a double-click sends
once" -- use ``SlowClient``, which blocks until the test releases it.
"""

import threading
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import QCoreApplication, QSettings, Qt, QThread
from PySide6.QtWidgets import QLineEdit
from pytestqt.qtbot import QtBot

from client.api_client import normalise_base_url
from client.main import MainWindow
from client.settings import ClientSettings
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.login_viewmodel import (
    LoginViewModel,
    validate_registration,
    validate_sign_in,
)
from client.views.login_view import REGISTER_PAGE, SIGN_IN_PAGE, LoginView
from tests.client.conftest import TEST_PASSWORD, unique_email

WAIT_MS = 8000


@pytest.fixture
def window(qtbot: QtBot, settings: ClientSettings, live_server: str) -> MainWindow:
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.login_view.server_input.setText(live_server)
    win.show()
    return win


def _registered_account(live_server: str, name: str = "Nick") -> str:
    email = unique_email()
    response = httpx.post(
        f"{live_server}/auth/register",
        json={"name": name, "email": email, "password": TEST_PASSWORD},
    )
    assert response.status_code == 201, response.text
    return email


def _sign_in(qtbot: QtBot, win: MainWindow, email: str, password: str = TEST_PASSWORD) -> None:
    view = win.login_view
    view.email_input.setText(email)
    view.password_input.setText(password)
    qtbot.mouseClick(view.sign_in_button, Qt.MouseButton.LeftButton)


def _on_home(win: MainWindow) -> bool:
    return win.home_view is not None and win.stack.currentWidget() is win.home_view


def _error(view: LoginView) -> str:
    # isHidden, not isVisible: a label in a window that was never shown is
    # "not visible" even after setVisible(True).
    return "" if view.error_label.isHidden() else view.error_label.text()


# ------------------------------------------------- form rules (no network)


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [
        ("", "pw", "Enter your email."),
        ("   ", "pw", "Enter your email."),
        ("nick", "pw", "That doesn't look like an email address."),
        ("nick@example", "pw", "That doesn't look like an email address."),
        ("ni ck@example.com", "pw", "That doesn't look like an email address."),
        ("nick@example.com", "", "Enter your password."),
        ("nick@example.com", "x", None),  # sign-in does not enforce length: the server decides
    ],
)
def test_sign_in_form_rules(email: str, password: str, message: str | None) -> None:
    assert validate_sign_in(email, password) == message


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (("", "a@b.co", "tangerine-77", "tangerine-77"), "Enter your name."),
        (("   ", "a@b.co", "tangerine-77", "tangerine-77"), "Enter your name."),
        (
            ("N" * 101, "a@b.co", "tangerine-77", "tangerine-77"),
            "Name must be at most 100 characters.",
        ),
        (("Nick", "", "tangerine-77", "tangerine-77"), "Enter your email."),
        (
            ("Nick", "a@b", "tangerine-77", "tangerine-77"),
            "That doesn't look like an email address.",
        ),
        (("Nick", "a@b.co", "short", "short"), "Password must be at least 8 characters."),
        (("Nick", "a@b.co", "p" * 129, "p" * 129), "Password must be at most 128 characters."),
        (("Nick", "a@b.co", "tangerine-77", "tangerine-78"), "Passwords don't match."),
        (("Nick", "a@b.co", "tangerine-77", ""), "Passwords don't match."),
        (("Nick", "a@b.co", "pässwörd🔒", "pässwörd🔒"), None),
        (("Nick", "a@b.co", "   tangerine   ", "   tangerine   "), None),  # spaces count
        (("Nick", "a@b.co", "        ", "        "), "Password can't be one character repeated."),
        (
            ("Nick", "a@b.co", "Password123", "Password123"),
            "That password is too common. Choose something harder to guess.",
        ),
        (("Nick", "nick@b.co", "nick@b.co", "nick@b.co"), "Password can't be your email address."),
        (("Nick Haines", "n@b.co", "nick haines", "nick haines"), "Password can't be your name."),
    ],
)
def test_registration_form_rules(fields: tuple, message: str | None) -> None:
    assert validate_registration(*fields) == message


def test_form_errors_show_without_contacting_the_server(
    qtbot: QtBot, settings: ClientSettings, dead_server: str
) -> None:
    """Pointed at a dead host: if the form check contacted it, we'd see "Can't reach"."""
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.login_view.server_input.setText(dead_server)
    _sign_in(qtbot, win, "not-an-email", "pw")
    assert _error(win.login_view) == "That doesn't look like an email address."
    assert not win.login_viewmodel.busy


def test_an_invalid_server_address_is_reported(qtbot: QtBot, window: MainWindow) -> None:
    window.login_view.server_input.setText("not a url")
    _sign_in(qtbot, window, "a@example.com")
    assert "not a valid server address" in _error(window.login_view)


def test_the_password_fields_hide_what_is_typed(window: MainWindow) -> None:
    view = window.login_view
    for field in (view.password_input, view.register_password_input, view.confirm_input):
        assert field.echoMode() == QLineEdit.EchoMode.Password


# ---------------------------------------------------------------- sign in


def test_signing_in_shows_the_home_screen(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server, name="Nick")
    _sign_in(qtbot, window, email)

    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    assert window.home_view.signed_in_label.full_text == "Signed in as Nick (Member)"
    assert live_server in window.home_view.server_label.full_text
    assert "Nick" in window.windowTitle()
    assert window.login_view.password_input.text() == ""


def test_pressing_enter_in_the_password_field_signs_in(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server)
    window.login_view.email_input.setText(email)
    window.login_view.password_input.setText(TEST_PASSWORD)
    qtbot.keyClick(window.login_view.password_input, Qt.Key.Key_Return)
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)


def test_the_email_is_matched_ignoring_case_and_spaces(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server)
    _sign_in(qtbot, window, f"  {email.upper()} ")
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)


def test_a_wrong_password_shows_the_error_and_unlocks_the_form(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server)
    _sign_in(qtbot, window, email, "wrong-password")

    view = window.login_view
    qtbot.waitUntil(lambda: _error(view) == "Incorrect email or password", timeout=WAIT_MS)
    assert not _on_home(window)
    assert view.sign_in_button.isEnabled()
    assert view.sign_in_button.text() == "Sign in"
    assert view.password_input.isEnabled()


def test_an_unreachable_host_shows_a_clear_message(
    qtbot: QtBot, window: MainWindow, dead_server: str
) -> None:
    window.login_view.server_input.setText(dead_server)
    _sign_in(qtbot, window, "a@example.com")
    qtbot.waitUntil(lambda: "Can't reach the server" in _error(window.login_view), timeout=WAIT_MS)
    assert window.login_view.sign_in_button.isEnabled()


def test_a_server_address_without_http_works(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server)
    window.login_view.server_input.setText(live_server.removeprefix("http://") + "/")
    _sign_in(qtbot, window, email)
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)


# ---------------------------------------------- busy state (controlled timing)


class SlowClient:
    """Stands in for ApiClient; ``login`` blocks until the test calls ``release``."""

    def __init__(self, base_url: str) -> None:
        self.base_url = normalise_base_url(base_url)
        self.calls = 0
        self.ran_on_main_thread: bool | None = None
        self._gate = threading.Event()

    def release(self) -> None:
        self._gate.set()

    def login(self, email: str, password: str) -> dict:
        self.calls += 1
        self.ran_on_main_thread = QThread.currentThread() == QCoreApplication.instance().thread()
        self._gate.wait(5)
        return {"id": 1, "name": "Nick", "email": email, "role": "member"}


@pytest.fixture
def slow_login(qtbot: QtBot, settings: ClientSettings) -> tuple[LoginView, LoginViewModel, list]:
    clients: list[SlowClient] = []

    def factory(url: str) -> SlowClient:
        client = SlowClient(url)
        clients.append(client)
        return client

    viewmodel = LoginViewModel(runner=BackgroundRunner(), client_factory=factory)
    view = LoginView(viewmodel, settings)
    qtbot.addWidget(view)
    view.server_input.setText("http://127.0.0.1:9")
    view.email_input.setText("nick@example.com")
    view.password_input.setText(TEST_PASSWORD)
    yield view, viewmodel, clients
    for client in clients:
        client.release()


def test_the_form_is_locked_while_signing_in(qtbot: QtBot, slow_login: tuple) -> None:
    view, viewmodel, clients = slow_login
    qtbot.mouseClick(view.sign_in_button, Qt.MouseButton.LeftButton)

    assert viewmodel.busy
    assert not view.sign_in_button.isEnabled()
    assert view.sign_in_button.text() == "Signing in…"
    assert not view.email_input.isEnabled()

    with qtbot.waitSignal(viewmodel.signed_in, timeout=WAIT_MS):
        clients[0].release()
    assert view.sign_in_button.isEnabled()
    assert view.sign_in_button.text() == "Sign in"


def test_a_double_click_sends_only_one_request(qtbot: QtBot, slow_login: tuple) -> None:
    view, viewmodel, clients = slow_login
    view.submit_sign_in()
    view.submit_sign_in()  # the button is disabled, but Enter/a fast double-click can still fire
    qtbot.keyClick(view.password_input, Qt.Key.Key_Return)

    with qtbot.waitSignal(viewmodel.signed_in, timeout=WAIT_MS):
        clients[0].release()
    assert len(clients) == 1
    assert clients[0].calls == 1


def test_the_request_runs_off_the_ui_thread(qtbot: QtBot, slow_login: tuple) -> None:
    view, viewmodel, clients = slow_login
    view.submit_sign_in()
    # The UI thread is free while the request is blocked: it can process events.
    qtbot.wait(100)
    assert viewmodel.busy
    with qtbot.waitSignal(viewmodel.signed_in, timeout=WAIT_MS):
        clients[0].release()
    assert clients[0].ran_on_main_thread is False


# --------------------------------------------------------- create account


def _open_register_page(qtbot: QtBot, win: MainWindow) -> LoginView:
    view = win.login_view
    qtbot.mouseClick(view.show_register_button, Qt.MouseButton.LeftButton)
    assert view.current_page == REGISTER_PAGE
    return view


def test_creating_an_account_signs_in_as_a_member(qtbot: QtBot, window: MainWindow) -> None:
    view = _open_register_page(qtbot, window)
    view.name_input.setText("  Kaleb  ")
    view.register_email_input.setText(unique_email("kaleb"))
    view.register_password_input.setText(TEST_PASSWORD)
    view.confirm_input.setText(TEST_PASSWORD)
    qtbot.mouseClick(view.create_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    assert window.home_view.signed_in_label.full_text == "Signed in as Kaleb (Member)"


def test_mismatched_passwords_are_caught_before_sending(qtbot: QtBot, window: MainWindow) -> None:
    view = _open_register_page(qtbot, window)
    view.name_input.setText("Kaleb")
    view.register_email_input.setText(unique_email())
    view.register_password_input.setText(TEST_PASSWORD)
    view.confirm_input.setText(TEST_PASSWORD + "x")
    qtbot.keyClick(view.confirm_input, Qt.Key.Key_Return)
    assert _error(view) == "Passwords don't match."
    assert not window.login_viewmodel.busy


def test_an_email_already_registered_is_reported(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server)
    view = _open_register_page(qtbot, window)
    view.name_input.setText("Copycat")
    view.register_email_input.setText(email)
    view.register_password_input.setText(TEST_PASSWORD)
    view.confirm_input.setText(TEST_PASSWORD)
    qtbot.mouseClick(view.create_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: "already registered" in _error(view), timeout=WAIT_MS)
    assert view.current_page == REGISTER_PAGE


def test_switching_pages_clears_the_error_and_carries_the_email(
    qtbot: QtBot, window: MainWindow
) -> None:
    view = window.login_view
    view.email_input.setText("nick@example.com")
    _sign_in(qtbot, window, "nick@example.com", "")
    assert _error(view) == "Enter your password."

    _open_register_page(qtbot, window)
    assert _error(view) == ""
    assert view.register_email_input.text() == "nick@example.com"

    view.register_email_input.setText("other@example.com")
    qtbot.mouseClick(view.show_sign_in_button, Qt.MouseButton.LeftButton)
    assert view.current_page == SIGN_IN_PAGE
    assert view.email_input.text() == "other@example.com"


# --------------------------------------------------------------- sign out


def test_signing_out_returns_to_a_clean_login_and_revokes_the_token(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server)
    _sign_in(qtbot, window, email)
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    token = window.home_viewmodel.session.client.token

    qtbot.mouseClick(window.home_view.sign_out_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.login_view, timeout=WAIT_MS)
    assert window.home_view is None
    assert window.login_view.password_input.text() == ""
    assert window.login_view.email_input.text() == email
    assert window.windowTitle() == "Kairos"
    response = httpx.get(f"{live_server}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_signing_out_works_even_if_the_host_is_gone(
    qtbot: QtBot, window: MainWindow, live_server: str, dead_server: str
) -> None:
    _sign_in(qtbot, window, _registered_account(live_server))
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    window.home_viewmodel.session.client.base_url = dead_server

    qtbot.mouseClick(window.home_view.sign_out_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.stack.currentWidget() is window.login_view, timeout=WAIT_MS)


def test_signing_in_again_after_signing_out(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    email = _registered_account(live_server)
    _sign_in(qtbot, window, email)
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    qtbot.mouseClick(window.home_view.sign_out_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: window.home_view is None, timeout=WAIT_MS)

    _sign_in(qtbot, window, email)
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)


def test_closing_the_window_while_signed_in_revokes_the_token(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    _sign_in(qtbot, window, _registered_account(live_server))
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    token = window.home_viewmodel.session.client.token

    window.close()

    response = httpx.get(f"{live_server}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


# --------------------------------------------------------------- messages


def test_messages_are_sent_under_the_users_name(
    qtbot: QtBot, window: MainWindow, live_server: str
) -> None:
    _sign_in(qtbot, window, _registered_account(live_server, name="Messenger"))
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    home = window.home_view

    home.message_input.setText("hello from the test")
    qtbot.keyClick(home.message_input, Qt.Key.Key_Return)

    qtbot.waitUntil(lambda: "You: hello from the test" in home.log.toPlainText(), timeout=WAIT_MS)
    assert home.message_input.text() == ""
    token = window.home_viewmodel.session.client.token
    stored = httpx.get(
        f"{live_server}/messages", headers={"Authorization": f"Bearer {token}"}
    ).json()
    assert any(m["sender"] == "Messenger" and m["content"] == "hello from the test" for m in stored)


def test_a_failed_send_shows_an_error_and_keeps_the_text(
    qtbot: QtBot, window: MainWindow, live_server: str, dead_server: str
) -> None:
    _sign_in(qtbot, window, _registered_account(live_server))
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)
    window.home_viewmodel.session.client.base_url = dead_server
    home = window.home_view

    home.message_input.setText("will not arrive")
    qtbot.mouseClick(home.send_button, Qt.MouseButton.LeftButton)

    qtbot.waitUntil(lambda: not home.error_label.isHidden(), timeout=WAIT_MS)
    assert home.error_label.text().startswith("Send failed: Can't reach")
    assert home.message_input.text() == "will not arrive"


# --------------------------------------------------------------- settings


def test_the_server_and_email_are_remembered_for_next_launch(
    qtbot: QtBot, window: MainWindow, settings: ClientSettings, live_server: str
) -> None:
    email = _registered_account(live_server)
    _sign_in(qtbot, window, email)
    qtbot.waitUntil(lambda: _on_home(window), timeout=WAIT_MS)

    next_launch = MainWindow(settings)
    qtbot.addWidget(next_launch)
    assert next_launch.login_view.server_input.text() == live_server
    assert next_launch.login_view.email_input.text() == email
    assert next_launch.login_view.password_input.text() == ""


def test_nothing_secret_is_written_to_the_settings_file(
    qtbot: QtBot, tmp_path: Path, live_server: str
) -> None:
    ini = tmp_path / "secret-check.ini"
    win = MainWindow(ClientSettings(QSettings(str(ini), QSettings.Format.IniFormat)))
    qtbot.addWidget(win)
    win.login_view.server_input.setText(live_server)
    _sign_in(qtbot, win, _registered_account(live_server))
    qtbot.waitUntil(lambda: _on_home(win), timeout=WAIT_MS)
    token = win.home_viewmodel.session.client.token

    saved = ini.read_text()
    assert TEST_PASSWORD not in saved
    assert token not in saved
    assert "password" not in saved.lower()
    assert "token" not in saved.lower()
