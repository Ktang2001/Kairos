"""A sign-in that stops being accepted while the app is open sends the user back
to sign in, instead of every page showing "401" (found in use).

The sign-in is ended for real on the live test server (``/auth/logout`` sent
with the same token from outside the app), the way an expired session or a
server update ending every session looks to the app.
"""

import tempfile
from pathlib import Path

import httpx
import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient, ApiError
from client.theme import ThemeManager
from client.views.app_shell import AppShell
from tests.client.conftest import SETUP_TIMEOUT, TEST_PASSWORD, unique_email

TEAMS_ROW = 2


def _signed_in_client(live_server: str) -> ApiClient:
    """A real account on the live server and a client holding its token."""
    body = httpx.post(
        f"{live_server}/auth/signup",
        json={"name": "Max", "email": unique_email("expiry"), "password": TEST_PASSWORD},
        timeout=SETUP_TIMEOUT,
    ).json()
    return ApiClient(base_url=live_server, token=body["token"], user_id=body["id"])


def _end_sign_in(live_server: str, token: str) -> None:
    """End the session on the server, from outside the app."""
    response = httpx.post(
        f"{live_server}/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
        timeout=SETUP_TIMEOUT,
    )
    assert response.status_code == 204


def _theme_manager() -> ThemeManager:
    ini = Path(tempfile.mkdtemp()) / "theme.ini"
    return ThemeManager(settings=QSettings(str(ini), QSettings.Format.IniFormat))


# ------------------------------------------------------------- ApiClient


def test_a_refused_token_is_reported(live_server: str) -> None:
    client = _signed_in_client(live_server)
    reported: list[bool] = []
    client.on_session_expired = lambda: reported.append(True)
    client.list_teams()
    assert reported == []

    _end_sign_in(live_server, client.token)
    with pytest.raises(ApiError) as failure:
        client.list_teams()
    assert failure.value.status_code == 401
    assert reported == [True]


def test_sign_in_routes_and_other_errors_are_not_reported(live_server: str) -> None:
    client = _signed_in_client(live_server)
    reported: list[bool] = []
    client.on_session_expired = lambda: reported.append(True)
    # 404 and 403 aren't an expired sign-in.
    with pytest.raises(ApiError):
        client.get_team(999_999)
    with pytest.raises(ApiError):
        client.list_users()
    # A 401 from /auth/... (e.g. logging out twice) isn't either.
    client.logout()
    client.token = "already-ended"
    client._http.post(f"{live_server}/auth/logout", headers=client._auth_headers())
    # And with no token there is no sign-in to expire.
    client.token = None
    client._http.get(f"{live_server}/teams")
    assert reported == []


# --------------------------------------------------------------- AppShell


def test_the_app_window_reports_an_expired_sign_in_once(qtbot: QtBot, live_server: str) -> None:
    client = _signed_in_client(live_server)
    expired: list[bool] = []
    shell = AppShell(
        client,
        display_name="Max",
        server_label="Test Server",
        on_switch_account=lambda: None,
        theme_manager=_theme_manager(),
        on_session_expired=lambda: expired.append(True),
    )
    qtbot.addWidget(shell)
    shell.show()
    qtbot.waitUntil(lambda: not shell.dashboard_viewmodel.busy, timeout=8000)

    _end_sign_in(live_server, client.token)
    # Several pages fail at once: the Dashboard and Teams both reload.
    shell.nav_list.setCurrentRow(TEAMS_ROW)
    shell.dashboard_viewmodel.refresh()
    qtbot.waitUntil(lambda: expired == [True], timeout=8000)
    qtbot.waitUntil(lambda: not shell.teams_viewmodel.busy, timeout=8000)
    assert expired == [True]
    assert not shell.refresh_timer.isActive()


def test_a_closed_app_window_stops_listening(qtbot: QtBot, live_server: str) -> None:
    client = _signed_in_client(live_server)
    shell = AppShell(
        client,
        display_name="Max",
        server_label="Test Server",
        on_switch_account=lambda: None,
        theme_manager=_theme_manager(),
        on_session_expired=lambda: None,
    )
    qtbot.addWidget(shell)
    assert client.on_session_expired is not None
    shell.close()
    assert client.on_session_expired is None
