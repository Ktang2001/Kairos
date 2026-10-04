"""Client paths that ordinary use rarely reaches: odd server replies, the
app's own start-up, background work finishing at awkward moments, the real
yes/no dialog the other tests replace, and saying No to a confirmation.
"""

from types import SimpleNamespace

import httpx
import pytest
from PySide6.QtWidgets import QMessageBox
from pytestqt.qtbot import QtBot

from client import main as client_main
from client.api_client.client import _error_message
from client.viewmodels import background
from client.viewmodels.background import BackgroundRunner, wait_until_idle
from client.viewmodels.session import Session
from client.viewmodels.teams_viewmodel import TeamsViewModel
from client.views import teams_view as teams_view_module
from client.views.teams_view import TeamsView

ME = {"id": 1, "name": "Nick", "email": "nick@example.com", "role": "member"}
TEAM = {"id": 5, "name": "Alpha", "lead": ME, "members": [ME]}


def _session() -> Session:
    return Session(client=SimpleNamespace(token="t", base_url="http://127.0.0.1:9"), user=ME)


# ------------------------------------------------------- server replies


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

        def setWindowIcon(self, _icon) -> None:
            pass

        def setDesktopFileName(self, _name) -> None:
            pass

        def exec(self) -> int:
            started.append("exec")
            return 0

    class FakeWindow:
        def __init__(self, **_kwargs) -> None:
            pass

        def show(self) -> None:
            started.append("window")

    monkeypatch.setattr(client_main, "QApplication", FakeApp)
    monkeypatch.setattr(
        client_main, "MainThreadGarbageCollector", lambda _app: started.append("gc")
    )
    monkeypatch.setattr(client_main, "ConnectWindow", FakeWindow)
    monkeypatch.setattr(client_main, "ThemeManager", lambda: SimpleNamespace(apply=lambda: None))

    with pytest.raises(SystemExit) as exit_info:
        client_main.main()
    assert exit_info.value.code == 0
    assert started == ["app", "gc", "window", "exec"]  # collector before any request


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


@pytest.mark.parametrize(
    "action", ["_make_lead", "_delete", "_leave"], ids=["lead", "delete", "leave"]
)
def test_saying_no_to_a_confirmation_sends_nothing(qtbot: QtBot, action: str) -> None:
    teams = TeamsView(TeamsViewModel(_session()))
    qtbot.addWidget(teams)
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
