"""Tests for finishing context.md goal #3: the app keeps its data honest and
handles a lost connection or a dead session cleanly.

* expired / revoked session -> back to login, with a message
* host unreachable -> one banner with Retry, clears by itself
* "Loading..." until the first answer arrives
* auto-refresh (timer and tab switch) without trampling what you're doing
* "Sign out everywhere"

All against the real API (``live_server``) through the real ``MainWindow``.
"""

import httpx
import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient
from client.main import SESSION_EXPIRED_MESSAGE, MainWindow
from client.settings import ClientSettings
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import Session
from client.views.home_view import AUTO_REFRESH_MS, HomeView
from shared.roles import ROLE_ADMIN, ROLE_PROJECT_LEAD
from tests.client.conftest import TEST_PASSWORD, set_live_role, unique_email

WAIT_MS = 8000


def _register(live_server: str, name: str, role: str | None = None) -> str:
    email = unique_email(name.lower())
    ApiClient(live_server).register(name, email, TEST_PASSWORD)
    if role:
        set_live_role(email, role)
    return email


def _signed_in_window(
    qtbot: QtBot, settings: ClientSettings, live_server: str, email: str
) -> MainWindow:
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.show()
    view = win.login_view
    view.server_input.setText(live_server)
    view.email_input.setText(email)
    view.password_input.setText(TEST_PASSWORD)
    view.submit_sign_in()
    qtbot.waitUntil(lambda: win.home_view is not None, timeout=WAIT_MS)
    _settle(qtbot, win.home_view)
    return win


def _settle(qtbot: QtBot, home: HomeView) -> None:
    qtbot.waitUntil(
        lambda: not home.teams_viewmodel.busy and not home.users_viewmodel.busy, timeout=WAIT_MS
    )


def _on_login(win: MainWindow) -> bool:
    return win.home_view is None and win.stack.currentWidget() is win.login_view


# ========================================================= session expiry


def test_a_session_ended_elsewhere_returns_to_login_with_a_message(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)

    # "Sign out everywhere" from another computer kills this window's token.
    other = ApiClient(live_server)
    other.login(email, TEST_PASSWORD)
    other.logout_everywhere()

    win.home_view.refresh_current_tab()
    qtbot.waitUntil(lambda: _on_login(win), timeout=WAIT_MS)

    view = win.login_view
    assert view.error_label.text() == SESSION_EXPIRED_MESSAGE
    assert not view.error_label.isHidden()
    assert view.email_input.text() == email
    assert view.password_input.text() == ""


def test_signing_back_in_after_expiry_works(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    win.home_viewmodel.session.client.token = "revoked-token"
    win.home_view.refresh_current_tab()
    qtbot.waitUntil(lambda: _on_login(win), timeout=WAIT_MS)

    win.login_view.password_input.setText(TEST_PASSWORD)
    win.login_view.submit_sign_in()
    qtbot.waitUntil(lambda: win.home_view is not None, timeout=WAIT_MS)
    _settle(qtbot, win.home_view)
    assert not win.home_view.offline


def test_the_expiry_message_clears_when_the_user_types(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    win.home_viewmodel.session.client.token = "revoked-token"
    win.home_view.refresh_current_tab()
    qtbot.waitUntil(lambda: _on_login(win), timeout=WAIT_MS)
    qtbot.keyClicks(win.login_view.password_input, "x")
    assert win.login_view.error_label.isHidden()


def test_a_wrong_password_at_login_is_not_treated_as_expiry(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = MainWindow(settings)
    qtbot.addWidget(win)
    view = win.login_view
    view.server_input.setText(live_server)
    view.email_input.setText(email)
    view.password_input.setText("wrong-password")
    view.submit_sign_in()
    qtbot.waitUntil(lambda: not view.error_label.isHidden(), timeout=WAIT_MS)
    assert view.error_label.text() == "Incorrect email or password"


# ========================================================= offline banner


def test_losing_the_host_shows_one_banner_and_retry_clears_it(
    qtbot: QtBot, settings: ClientSettings, live_server: str, dead_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    home = win.home_view
    assert not home.offline

    client = win.home_viewmodel.session.client
    client.base_url = dead_server  # the host goes away
    home.refresh_current_tab()
    qtbot.waitUntil(lambda: home.offline, timeout=WAIT_MS)
    assert "Can't reach the server" in home.offline_label.text()
    assert win.home_view is not None  # still signed in: being offline isn't expiry

    client.base_url = live_server  # the host comes back
    qtbot.mouseClick(home.retry_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: not home.offline, timeout=WAIT_MS)


def test_the_banner_clears_by_itself_on_the_next_good_request(
    qtbot: QtBot, settings: ClientSettings, live_server: str, dead_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    home = win.home_view
    client = win.home_viewmodel.session.client
    client.base_url = dead_server
    home.refresh_current_tab()
    qtbot.waitUntil(lambda: home.offline, timeout=WAIT_MS)

    client.base_url = live_server
    home.refresh_timer.timeout.emit()  # the next automatic refresh
    qtbot.waitUntil(lambda: not home.offline, timeout=WAIT_MS)


# ========================================================== loading states


def test_teams_says_loading_until_the_first_answer(qtbot: QtBot) -> None:
    session = Session(
        client=ApiClient("http://127.0.0.1:9"),
        user={"id": 1, "name": "N", "email": "n@x.co", "role": "member"},
    )
    home = HomeView(HomeViewModel(session))
    qtbot.addWidget(home)
    assert home.teams_view.empty_label.text() == "Loading your teams…"


def test_users_says_loading_until_the_first_answer(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    session = Session(
        client=ApiClient("http://127.0.0.1:9"),
        user={"id": 1, "name": "A", "email": "a@x.co", "role": ROLE_ADMIN},
    )
    home = HomeView(HomeViewModel(session))
    qtbot.addWidget(home)
    assert not home.users_view.loading_label.isHidden()


def test_loading_labels_go_away_once_loaded(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Ada", ROLE_ADMIN)
    win = _signed_in_window(qtbot, settings, live_server, email)
    home = win.home_view
    assert "Loading" not in home.teams_view.empty_label.text()
    assert home.users_view.loading_label.isHidden()


# ============================================================ auto-refresh


def test_auto_refresh_runs_every_30_seconds(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    assert AUTO_REFRESH_MS == 30_000
    assert win.home_view.refresh_timer.isActive()
    assert win.home_view.refresh_timer.interval() == AUTO_REFRESH_MS


def test_being_added_to_a_team_shows_up_on_the_next_refresh(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    home = win.home_view
    assert home.teams_viewmodel.teams == []

    lead = ApiClient(live_server)
    lead.register("Lena", unique_email("lena"), TEST_PASSWORD)
    set_live_role(lead.me()["email"], ROLE_PROJECT_LEAD)
    team = lead.create_team(f"Surprise {unique_email()}")
    lead.add_member(team["id"], email)

    home.refresh_timer.timeout.emit()
    qtbot.waitUntil(lambda: len(home.teams_viewmodel.teams) == 1, timeout=WAIT_MS)


def test_switching_tabs_refreshes_the_tab(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Ada", ROLE_ADMIN)
    win = _signed_in_window(qtbot, settings, live_server, email)
    home = win.home_view
    before = len(home.users_viewmodel.users)
    _register(live_server, "Newcomer")

    home.tabs.setCurrentWidget(home.users_view)
    qtbot.waitUntil(lambda: len(home.users_viewmodel.users) == before + 1, timeout=WAIT_MS)


@pytest.fixture
def lead_with_team(qtbot: QtBot, settings: ClientSettings, live_server: str):
    email = _register(live_server, "Lena", ROLE_PROJECT_LEAD)
    member = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    client = win.home_viewmodel.session.client
    team = client.create_team(f"Alpha {unique_email()}")
    client.add_member(team["id"], member)
    home = win.home_view
    home.teams_viewmodel.select_team(team["id"])
    _settle(qtbot, home)
    return win, home, team, member


def test_refresh_does_not_wipe_a_name_being_typed(qtbot: QtBot, lead_with_team) -> None:
    _win, home, _team, _member = lead_with_team
    box = home.teams_view.rename_input
    box.selectAll()
    qtbot.keyClicks(box, "Half-typed new na")

    home.refresh_current_tab()
    _settle(qtbot, home)
    assert box.text() == "Half-typed new na"


def test_refresh_updates_the_name_box_when_untouched(qtbot: QtBot, lead_with_team) -> None:
    win, home, team, _member = lead_with_team
    renamed = f"Renamed elsewhere {unique_email()}"
    win.home_viewmodel.session.client.rename_team(team["id"], renamed)

    home.refresh_current_tab()
    _settle(qtbot, home)
    assert home.teams_view.rename_input.text() == renamed


def test_refresh_keeps_the_selected_member_selected(qtbot: QtBot, lead_with_team) -> None:
    _win, home, _team, member = lead_with_team
    members = home.teams_view.members_list
    row = next(i for i in range(members.count()) if member in members.item(i).text())
    members.setCurrentRow(row)

    home.refresh_current_tab()
    _settle(qtbot, home)
    assert member in members.currentItem().text()
    assert home.teams_view.remove_member_button.isEnabled()


def test_signing_out_stops_auto_refresh(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    timer = win.home_view.refresh_timer
    qtbot.mouseClick(win.home_view.sign_out_button, Qt.MouseButton.LeftButton)
    assert not timer.isActive()
    qtbot.waitUntil(lambda: _on_login(win), timeout=WAIT_MS)


# ===================================================== sign out everywhere


def test_sign_out_everywhere_ends_every_session(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    laptop = ApiClient(live_server)
    laptop.login(email, TEST_PASSWORD)

    win = _signed_in_window(qtbot, settings, live_server, email)
    asked: list[str] = []
    win.home_view.confirm = lambda title, question: asked.append(question) or True
    qtbot.mouseClick(win.home_view.sign_out_everywhere_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: _on_login(win), timeout=WAIT_MS)

    assert asked and "every computer" in asked[0]
    response = httpx.get(
        f"{live_server}/auth/me", headers={"Authorization": f"Bearer {laptop.token}"}
    )
    assert response.status_code == 401


def test_cancelling_sign_out_everywhere_changes_nothing(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    win.home_view.confirm = lambda title, question: False
    qtbot.mouseClick(win.home_view.sign_out_everywhere_button, Qt.MouseButton.LeftButton)
    qtbot.wait(200)
    assert win.home_view is not None
    assert win.home_view.sign_out_everywhere_button.isEnabled()
    assert win.home_viewmodel.session.client.me()["email"] == email


def test_connection_trouble_is_reported_once_in_the_banner_not_in_the_tab(
    qtbot: QtBot, settings: ClientSettings, live_server: str, dead_server: str
) -> None:
    email = _register(live_server, "Max")
    win = _signed_in_window(qtbot, settings, live_server, email)
    home = win.home_view
    win.home_viewmodel.session.client.base_url = dead_server
    home.refresh_current_tab()
    qtbot.waitUntil(lambda: home.offline, timeout=WAIT_MS)
    _settle(qtbot, home)
    assert home.teams_view.error_label.isHidden()


def test_other_errors_still_show_in_the_tab(
    qtbot: QtBot, settings: ClientSettings, live_server: str
) -> None:
    email = _register(live_server, "Lena", ROLE_PROJECT_LEAD)
    win = _signed_in_window(qtbot, settings, live_server, email)
    home = win.home_view
    home.teams_view.new_team_input.setText("   ")
    home.teams_view._create()
    assert home.teams_view.error_label.text() == "Enter a team name."
    assert not home.teams_view.error_label.isHidden()
