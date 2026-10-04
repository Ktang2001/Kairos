"""Client paths that ordinary use rarely reaches: odd server replies, the
app's own start-up, dialogs the other tests replace, and "nothing to do"
branches (signing out when not signed in, removing an attachment that
isn't there, saying No to a confirmation).
"""

from types import SimpleNamespace

import httpx
import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from client import main as client_main
from client.api_client import ApiError
from client.api_client.client import _error_message, normalise_base_url
from client.settings import ClientSettings
from client.viewmodels import background
from client.viewmodels.attachments import AttachmentKind
from client.viewmodels.background import BackgroundRunner, wait_until_idle
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import LoginViewModel, Session
from client.viewmodels.session_events import SessionEvents
from client.views import home_view as home_view_module
from client.views import teams_view as teams_view_module
from client.views.home_view import HomeView
from client.views.login_view import LoginView

ME = {"id": 1, "name": "Nick", "email": "nick@example.com", "role": "member"}
TEAM = {"id": 5, "name": "Alpha", "lead": ME, "members": [ME]}


def _session() -> Session:
    return Session(client=SimpleNamespace(token="t", base_url="http://127.0.0.1:9"), user=ME)


# ------------------------------------------------------- server replies


def test_an_address_httpx_cannot_parse_is_explained() -> None:
    with pytest.raises(ApiError, match="not a valid server address"):
        normalise_base_url("http://[zz]:80")


def test_an_error_page_that_is_not_json_still_gives_a_message() -> None:
    # e.g. a proxy or Wi-Fi login page answering instead of Kairos
    response = httpx.Response(502, text="<html>Bad gateway</html>")
    assert _error_message(response) == "The server returned an error (502)."


def test_an_empty_validation_error_list_still_gives_a_message() -> None:
    response = httpx.Response(422, json={"detail": []})
    assert _error_message(response) == "The server returned an error (422)."


# ------------------------------------------------------------- the app


def test_the_app_starts_with_main_thread_collection_and_a_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[str] = []

    class FakeApp:
        def __init__(self, _argv) -> None:
            started.append("app")

        def exec(self) -> int:
            started.append("exec")
            return 0

    class FakeWindow:
        def show(self) -> None:
            started.append("window")

    monkeypatch.setattr(client_main, "QApplication", FakeApp)
    monkeypatch.setattr(
        client_main, "MainThreadGarbageCollector", lambda _app: started.append("gc")
    )
    monkeypatch.setattr(client_main, "MainWindow", FakeWindow)

    with pytest.raises(SystemExit) as exit_info:
        client_main.main()
    assert exit_info.value.code == 0
    assert started == ["app", "gc", "window", "exec"]  # collector before any request


def test_session_expiry_while_signed_out_does_nothing(
    qtbot: QtBot, settings: ClientSettings
) -> None:
    win = client_main.MainWindow(settings)
    qtbot.addWidget(win)
    win._on_session_expired()  # a late 401 after signing out
    win._show_login()  # and returning to login when already there
    assert win.stack.currentWidget() is win.login_view
    assert win.login_view.error_label.isHidden()


# ------------------------------------------------------- background work


def test_a_result_finishing_during_shutdown_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    def gone(*_args) -> None:
        raise RuntimeError("Internal C++ object already deleted.")

    monkeypatch.setattr(
        background, "_dispatcher", SimpleNamespace(finished=SimpleNamespace(emit=gone))
    )
    background._work(10**9, [lambda: 1])  # no exception escapes


def test_a_result_with_no_dispatcher_yet_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background, "_dispatcher", None)
    background._work(10**9, [lambda: 1])


def test_waiting_also_covers_requests_started_by_a_result(qtbot: QtBot) -> None:
    # e.g. a queued refresh starting as the previous one is delivered
    runner = BackgroundRunner()
    done: list[str] = []
    runner.run(
        lambda: "first",
        lambda value: (
            done.append(value),
            runner.run(lambda: "second", done.append, done.append),
        ),
        done.append,
    )
    assert wait_until_idle(5)
    assert done == ["first", "second"]


def test_waiting_works_without_a_qt_application(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(background, "QCoreApplication", SimpleNamespace(instance=lambda: None))
    assert wait_until_idle(1)


# ------------------------------------------------------- "nothing to do"


def test_removing_an_attachment_that_is_not_there_changes_nothing() -> None:
    viewmodel = HomeViewModel(_session())
    changes: list[object] = []
    viewmodel.attachment_changed.connect(changes.append)
    viewmodel.clear_attachment()
    assert changes == []


def test_an_expired_session_is_reported_once(qtbot: QtBot) -> None:
    events = SessionEvents()
    fired: list[bool] = []
    events.expired.connect(lambda: fired.append(True))
    events._report_expired()
    events._report_expired()  # several requests refused at once
    qtbot.wait(10)
    assert fired == [True]


@pytest.mark.parametrize(
    "action", ["_make_lead", "_delete", "_leave"], ids=["lead", "delete", "leave"]
)
def test_saying_no_to_a_confirmation_sends_nothing(qtbot: QtBot, action: str) -> None:
    home = HomeView(HomeViewModel(_session()))
    qtbot.addWidget(home)
    teams = home.teams_view
    teams.viewmodel.team = dict(TEAM)
    teams._selected_member_id = lambda: 2
    teams._selected_member_name = lambda: "Max"
    teams.confirm = lambda *_args: False
    getattr(teams, action)()
    assert not teams.viewmodel.busy


# --------------------------------------- dialogs the other tests replace


@pytest.mark.parametrize(
    ("answer", "expected"),
    [(QMessageBox.StandardButton.Yes, True), (QMessageBox.StandardButton.No, False)],
)
def test_the_yes_no_dialog_returns_the_answer(
    monkeypatch: pytest.MonkeyPatch, answer, expected: bool
) -> None:
    monkeypatch.setattr(teams_view_module.QMessageBox, "question", lambda *_args: answer)
    assert teams_view_module.ask_yes_no(None, "Title", "Sure?") is expected


def test_the_file_picker_returns_the_chosen_path(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def picker(_parent, _title, _folder, file_filter):
        asked.append(file_filter)
        return "C:/pictures/logo.png", file_filter

    monkeypatch.setattr(home_view_module.QFileDialog, "getOpenFileName", picker)
    home = HomeView(HomeViewModel(_session()))
    qtbot.addWidget(home)
    assert home._open_file_dialog(AttachmentKind.IMAGE) == "C:/pictures/logo.png"
    assert "*.png" in asked[0]


# ------------------------------------------------------------ login page


@pytest.fixture
def login_view(qtbot: QtBot, settings: ClientSettings) -> LoginView:
    view = LoginView(LoginViewModel(), settings)
    qtbot.addWidget(view)
    return view


def test_with_everything_filled_in_the_cursor_goes_to_the_password(
    login_view: LoginView,
) -> None:
    focused: list[str] = []
    login_view.server_input.setText("127.0.0.1:8000")
    login_view.email_input.setText("nick@example.com")
    login_view.password_input.setText("secret-words")
    login_view.password_input.setFocus = lambda: focused.append("password")
    login_view.focus_first_empty_field()
    assert focused == ["password"]


def test_an_email_already_typed_on_the_register_page_is_kept(login_view: LoginView) -> None:
    login_view.register_email_input.setText("typed@example.com")
    login_view.email_input.setText("other@example.com")
    login_view.show_register_page()
    assert login_view.register_email_input.text() == "typed@example.com"


def test_going_back_with_no_register_email_keeps_the_sign_in_email(
    login_view: LoginView,
) -> None:
    login_view.email_input.setText("nick@example.com")
    login_view.show_sign_in_page()
    assert login_view.email_input.text() == "nick@example.com"


def test_typing_with_no_error_shown_does_not_touch_the_error(login_view: LoginView) -> None:
    cleared: list[bool] = []
    login_view.viewmodel.clear_error = lambda: cleared.append(True)
    login_view._clear_error_on_edit()
    assert cleared == []
