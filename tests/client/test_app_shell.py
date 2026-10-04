from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QPushButton

from client.api_client import ApiClient
from client.theme import ThemeManager
from client.views.app_shell import AppShell


def _isolated_theme_manager(tmp_path) -> ThemeManager:
    ini_path = str(tmp_path / "test_theme.ini")
    return ThemeManager(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def test_defaults_to_dashboard_and_switches_to_chat(qtbot, monkeypatch, tmp_path) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
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
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
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
    api = ApiClient(base_url="http://localhost:8000", user_id=2)
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
    assert items == ["Dashboard", "Chat"]
    assert shell.server_settings_page is None


def test_admin_gets_server_settings_nav(qtbot, monkeypatch, tmp_path) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
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
    assert items == ["Dashboard", "Chat", "Server Settings"]
    assert shell.server_settings_page is not None

    shell.nav_list.setCurrentRow(2)
    assert shell.pages.currentWidget() is shell.server_settings_page
