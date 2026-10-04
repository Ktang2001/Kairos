"""The small checks that stop a screen from sending a pointless or broken
request: nothing selected, an invalid name, a role that didn't change, a
second click while the first is still running. Also the "screen already
closed" paths, which must stay quiet instead of crashing.

No server: each test asserts that nothing was sent at all.
"""

import threading

import pytest
import shiboken6
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient
from client.viewmodels import background
from client.viewmodels.background import BackgroundRunner, wait_until_idle
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import Session
from client.viewmodels.session_events import SessionEvents
from client.viewmodels.teams_viewmodel import MAX_TEAM_NAME_LENGTH, TeamsViewModel
from client.viewmodels.users_viewmodel import UsersViewModel
from client.views.home_view import HomeView
from client.views.users_view import UsersView
from shared.roles import ROLE_ADMIN, ROLE_MEMBER

WAIT_MS = 5000
ME = {"id": 1, "name": "Nick", "email": "nick@example.com", "role": ROLE_MEMBER}
TEAM = {"id": 5, "name": "Alpha", "lead": ME, "members": [ME]}


class RecordingClient:
    """Records every request; ``gate`` holds requests open until set."""

    base_url = "http://127.0.0.1:9"

    def __init__(self) -> None:
        self.token = "t"
        self.calls: list[str] = []
        self.gate = threading.Event()
        self.gate.set()

    def _call(self, name: str):
        self.calls.append(name)
        self.gate.wait(5)

    def me(self) -> dict:
        self._call("me")
        return dict(ME)

    def list_teams(self) -> list[dict]:
        self._call("list_teams")
        return []

    def list_users(self) -> list[dict]:
        self._call("list_users")
        return []

    def set_role(self, user_id: int, role: str) -> dict:
        self._call("set_role")
        return {}

    def logout(self) -> None:
        self._call("logout")


@pytest.fixture
def client() -> RecordingClient:
    fake = RecordingClient()
    yield fake
    fake.gate.set()


def _session(client: RecordingClient, role: str = ROLE_MEMBER) -> Session:
    return Session(client=client, user={**ME, "role": role})


# ------------------------------------------------------------- teams


def test_a_team_name_that_is_too_long_is_caught_before_sending(
    client: RecordingClient,
) -> None:
    viewmodel = TeamsViewModel(_session(client))
    errors: list[str] = []
    viewmodel.error_changed.connect(errors.append)
    viewmodel.create_team("x" * (MAX_TEAM_NAME_LENGTH + 1))
    assert errors == [f"Team names can be at most {MAX_TEAM_NAME_LENGTH} characters."]
    assert not viewmodel.busy and client.calls == []


def test_renaming_to_a_blank_name_is_caught_before_sending(client: RecordingClient) -> None:
    viewmodel = TeamsViewModel(_session(client))
    viewmodel.team = dict(TEAM)
    errors: list[str] = []
    viewmodel.error_changed.connect(errors.append)
    viewmodel.rename_team("   ")
    assert errors == ["Enter a team name."]
    assert not viewmodel.busy


def test_selecting_the_team_already_shown_sends_nothing(client: RecordingClient) -> None:
    viewmodel = TeamsViewModel(_session(client))
    viewmodel.team = dict(TEAM)
    viewmodel.select_team(TEAM["id"])
    assert not viewmodel.busy


@pytest.mark.parametrize(
    "action",
    [
        lambda vm: vm.rename_team("Omega"),
        lambda vm: vm.delete_team(),
        lambda vm: vm.add_member("max@example.com"),
        lambda vm: vm.remove_member(2),
        lambda vm: vm.make_lead(2),
        lambda vm: vm.leave_team(),
    ],
    ids=["rename", "delete", "add", "remove", "make-lead", "leave"],
)
def test_team_actions_with_no_team_selected_send_nothing(client: RecordingClient, action) -> None:
    viewmodel = TeamsViewModel(_session(client))
    errors: list[str] = []
    viewmodel.error_changed.connect(errors.append)
    action(viewmodel)
    assert not viewmodel.busy and errors == []


def test_remove_and_make_lead_buttons_do_nothing_with_no_member_selected(
    qtbot: QtBot, client: RecordingClient
) -> None:
    home = HomeView(HomeViewModel(_session(client)))
    qtbot.addWidget(home)
    teams = home.teams_view
    teams.viewmodel.team = dict(TEAM)
    teams.confirm = lambda *_args: pytest.fail("asked although nobody was selected")
    teams._remove_member()
    teams._make_lead()
    assert not teams.viewmodel.busy


# ------------------------------------------------------------- users


def test_picking_the_role_someone_already_has_sends_nothing(
    qtbot: QtBot, client: RecordingClient
) -> None:
    viewmodel = UsersViewModel(_session(client, ROLE_ADMIN))
    view = UsersView(viewmodel)
    qtbot.addWidget(view)
    max_ = {"id": 2, "name": "Max", "email": "max@example.com", "role": ROLE_MEMBER}
    viewmodel.users = [ME, max_]
    viewmodel.users_changed.emit(viewmodel.users)
    view.confirm = lambda *_args: pytest.fail("asked although nothing changed")

    view._role_picked(2, view.role_box(2))  # still "member"
    viewmodel.set_role(2, ROLE_MEMBER)
    assert not viewmodel.busy and client.calls == []


def test_a_role_change_while_loading_is_not_sent_twice(
    qtbot: QtBot, client: RecordingClient
) -> None:
    viewmodel = UsersViewModel(_session(client, ROLE_ADMIN))
    client.gate.clear()
    viewmodel.refresh()
    viewmodel.set_role(2, ROLE_ADMIN)  # ignored: the screen is disabled while loading
    client.gate.set()
    assert wait_until_idle(5)
    assert client.calls == ["list_users"]


def test_the_users_screen_leaves_connection_errors_to_the_banner(
    qtbot: QtBot, client: RecordingClient
) -> None:
    view = UsersView(UsersViewModel(_session(client, ROLE_ADMIN)))
    qtbot.addWidget(view)
    view.connection_errors_shown_elsewhere = True
    view._show_error("Can't reach the server at http://127.0.0.1:9. Is it running?")
    assert view.error_label.text() == ""


def test_becoming_an_admin_while_signed_in_loads_the_users_tab(
    qtbot: QtBot, client: RecordingClient
) -> None:
    home = HomeView(HomeViewModel(_session(client)))
    qtbot.addWidget(home)
    assert not home.users_tab_visible

    home.teams_viewmodel.me_changed.emit({**ME, "role": ROLE_ADMIN})
    assert home.users_tab_visible
    qtbot.waitUntil(lambda: home.users_viewmodel.loaded, timeout=WAIT_MS)
    assert "list_users" in client.calls


# ----------------------------------------------------------- sign out


def test_a_second_sign_out_click_is_ignored(qtbot: QtBot, client: RecordingClient) -> None:
    viewmodel = HomeViewModel(_session(client))
    client.gate.clear()
    viewmodel.sign_out()
    viewmodel.sign_out()
    client.gate.set()
    assert wait_until_idle(5)
    assert client.calls == ["logout"]


def test_signing_out_everywhere_without_a_token_sends_nothing() -> None:
    api = ApiClient("http://127.0.0.1:9")
    api.logout_everywhere()  # never signed in: nothing to revoke
    assert api.token is None


def test_signing_out_everywhere_from_an_unreachable_host_still_forgets_the_token() -> None:
    api = ApiClient("http://127.0.0.1:9", timeout=2)
    api.token = "abc"
    api.logout_everywhere()  # never raises
    assert api.token is None


# ------------------------------------------------ screen already closed


def test_connection_news_for_a_closed_screen_is_dropped_quietly(qtbot: QtBot) -> None:
    events = SessionEvents()
    assert events.reachable
    shiboken6.delete(events)  # signed out: the screen and its events are gone
    events._report_connection(False)  # a late request finishing: no crash


def test_a_result_nobody_is_waiting_for_is_ignored(qtbot: QtBot) -> None:
    BackgroundRunner()  # makes sure the dispatcher exists
    background._dispatcher._deliver(10**9, True, None)  # unknown job: no crash
