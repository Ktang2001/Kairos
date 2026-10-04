from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPushButton

from client.api_client import ApiClient
from client.theme import ThemeManager
from client.views.app_shell import AppShell


def _isolated_theme_manager(tmp_path) -> ThemeManager:
    ini_path = str(tmp_path / "test_theme.ini")
    return ThemeManager(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def test_defaults_to_dashboard_and_switches_to_chat(qtbot, monkeypatch, tmp_path) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1, token="tok-1")
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])

    switched = []
    shell = AppShell(
        api,
        display_name="Alice",
        server_label="Kairos Server",
        on_switch_account=lambda: switched.append(True),
        theme_manager=_isolated_theme_manager(tmp_path),
    )
    qtbot.addWidget(shell)

    assert shell.pages.currentWidget() is shell.dashboard_page
    assert "Alice" in shell.header_label.text()
    assert "Kairos Server" in shell.header_label.text()

    shell.nav_list.setCurrentRow(1)

    assert shell.pages.currentWidget() is shell.chat_page


def test_switch_account_button_invokes_callback(qtbot, monkeypatch, tmp_path) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1, token="tok-1")
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])

    switched = []
    shell = AppShell(
        api,
        display_name="Alice",
        server_label="Kairos Server",
        on_switch_account=lambda: switched.append(True),
        theme_manager=_isolated_theme_manager(tmp_path),
    )
    qtbot.addWidget(shell)

    button = next(
        b for b in shell.findChildren(QPushButton) if b.text() == "Switch Server / Account"
    )
    button.click()

    assert switched == [True]


def test_non_admin_does_not_get_server_settings_nav(qtbot, monkeypatch, tmp_path) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=2, token="tok-2")
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])

    shell = AppShell(
        api,
        display_name="Bob",
        server_label="Kairos Server",
        on_switch_account=lambda: None,
        is_admin=False,
        theme_manager=_isolated_theme_manager(tmp_path),
    )
    qtbot.addWidget(shell)

    items = [shell.nav_list.item(i).text() for i in range(shell.nav_list.count())]
    assert items == ["Dashboard", "Chat", "Teams"]
    assert shell.server_settings_page is None
    assert shell.users_page is None


def test_admin_gets_server_settings_nav(qtbot, monkeypatch, tmp_path) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1, token="tok-1")
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(
        ApiClient,
        "get_server_info",
        lambda self: {"display_name": "Kairos Server", "max_upload_size_bytes": 1024},
    )

    shell = AppShell(
        api,
        display_name="Alice",
        server_label="Kairos Server",
        on_switch_account=lambda: None,
        is_admin=True,
        theme_manager=_isolated_theme_manager(tmp_path),
    )
    qtbot.addWidget(shell)

    items = [shell.nav_list.item(i).text() for i in range(shell.nav_list.count())]
    assert items == ["Dashboard", "Chat", "Teams", "Users", "Server Settings"]
    assert shell.server_settings_page is not None

    shell.nav_list.setCurrentRow(4)
    assert shell.pages.currentWidget() is shell.server_settings_page


def _shell(qtbot, tmp_path, monkeypatch, *, is_admin: bool, calls: list[str]) -> AppShell:
    """An app window whose team/user requests are recorded instead of sent."""
    api = ApiClient(base_url="http://localhost:8000", user_id=1, token="tok-1")
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(
        ApiClient,
        "get_server_info",
        lambda self: {"display_name": "Kairos Server", "max_upload_size_bytes": 1024},
    )
    me = {"id": 1, "name": "Alice", "email": "a@x.co", "role": "admin" if is_admin else "member"}
    monkeypatch.setattr(ApiClient, "me", lambda self: calls.append("me") or me)
    monkeypatch.setattr(ApiClient, "list_teams", lambda self: calls.append("list_teams") or [])
    monkeypatch.setattr(ApiClient, "list_users", lambda self: calls.append("list_users") or [me])
    shell = AppShell(
        api,
        display_name="Alice",
        server_label="Kairos Server",
        on_switch_account=lambda: None,
        is_admin=is_admin,
        theme_manager=_isolated_theme_manager(tmp_path),
    )
    qtbot.addWidget(shell)
    return shell


def test_teams_and_users_load_only_when_opened(qtbot, monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    shell = _shell(qtbot, tmp_path, monkeypatch, is_admin=True, calls=calls)
    assert calls == []  # signing in doesn't wait on these pages

    shell.nav_list.setCurrentRow(2)
    assert shell.pages.currentWidget() is shell.teams_page
    qtbot.waitUntil(lambda: shell.teams_viewmodel.loaded, timeout=5000)
    assert "list_teams" in calls

    shell.nav_list.setCurrentRow(3)
    assert shell.pages.currentWidget() is shell.users_page
    qtbot.waitUntil(lambda: shell.users_viewmodel.loaded, timeout=5000)
    assert "list_users" in calls


def test_the_timer_reloads_only_the_page_showing(qtbot, monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    shell = _shell(qtbot, tmp_path, monkeypatch, is_admin=False, calls=calls)
    shell.refresh_current_page()  # on the Dashboard: nothing to reload
    assert calls == []
    shell.nav_list.setCurrentRow(2)
    qtbot.waitUntil(lambda: shell.teams_viewmodel.loaded, timeout=5000)
    calls.clear()
    shell.refresh_timer.timeout.emit()
    qtbot.waitUntil(lambda: "list_teams" in calls, timeout=5000)
