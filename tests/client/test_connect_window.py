from PySide6.QtCore import QSettings, Qt

from client.api_client import ApiClient
from client.net.discovery_listener import DiscoveredServer
from client.theme import ThemeManager
from client.viewmodels.identity_viewmodel import IdentityViewModel
from client.viewmodels.server_list_viewmodel import ServerListViewModel
from client.views.auth_dialog import AuthDialog
from client.views.connect_window import ConnectWindow
from tests.client.conftest import StubDiscoveryListener


def _isolated_viewmodel(tmp_path) -> ServerListViewModel:
    ini_path = str(tmp_path / "test_settings.ini")
    return ServerListViewModel(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def _isolated_identity_viewmodel(tmp_path) -> IdentityViewModel:
    ini_path = str(tmp_path / "test_identity.ini")
    return IdentityViewModel(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def _isolated_theme_manager(tmp_path) -> ThemeManager:
    ini_path = str(tmp_path / "test_theme.ini")
    return ThemeManager(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def _make_window(
    tmp_path, server_list_vm=None, identity_vm=None, discovery_listener=None
) -> ConnectWindow:
    return ConnectWindow(
        server_list_vm=server_list_vm or _isolated_viewmodel(tmp_path),
        identity_vm=identity_vm or _isolated_identity_viewmodel(tmp_path),
        theme_manager=_isolated_theme_manager(tmp_path),
        discovery_listener=discovery_listener or StubDiscoveryListener(),
    )


def test_connection_failure_disables_sign_in(qtbot, monkeypatch, tmp_path) -> None:
    def _fail(self):
        import httpx

        raise httpx.ConnectError("refused")

    monkeypatch.setattr(ApiClient, "health", _fail)

    vm = _isolated_viewmodel(tmp_path)
    vm.add_server(host="10.0.0.1", port=9999)

    window = _make_window(tmp_path, server_list_vm=vm)
    qtbot.addWidget(window)

    tile = window._saved_tiles_layout.itemAt(0).widget()
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert window.api_client is None
    assert not window.sign_in_button.isEnabled()
    assert "Connection failed" in window.status_label.text()


def test_connecting_with_no_cached_identity_auto_opens_sign_in(
    qtbot, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )

    def _fake_exec(self):
        return AuthDialog.DialogCode.Rejected

    monkeypatch.setattr(AuthDialog, "exec", _fake_exec)

    vm = _isolated_viewmodel(tmp_path)
    vm.add_server(host="192.168.1.10", port=8000)

    window = _make_window(tmp_path, server_list_vm=vm)
    qtbot.addWidget(window)
    window.show()
    tile = window._saved_tiles_layout.itemAt(0).widget()
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    # Sign-in dialog auto-opened and was cancelled, so we stay on ConnectWindow.
    assert window.identity_label.text() == "Not signed in"
    assert window._app_shell is None
    assert not window.isHidden()


def test_signing_in_enters_app_shell(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(ApiClient, "get_my_profile", lambda self: {"role": "member"})

    def _fake_exec(self):
        self.result_user_id = 1
        self.result_user_name = "Alice"
        return AuthDialog.DialogCode.Accepted

    monkeypatch.setattr(AuthDialog, "exec", _fake_exec)

    vm = _isolated_viewmodel(tmp_path)
    vm.add_server(host="192.168.1.10", port=8000)
    identity_vm = _isolated_identity_viewmodel(tmp_path)

    window = _make_window(tmp_path, server_list_vm=vm, identity_vm=identity_vm)
    qtbot.addWidget(window)
    window.show()
    tile = window._saved_tiles_layout.itemAt(0).widget()
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert window._app_shell is not None
    assert window.isHidden()
    assert "Alice" in window._app_shell.header_label.text()
    assert identity_vm.load_cached_identity(vm.list_servers()[0].id) == (1, "Alice")


def test_cached_identity_auto_enters_app_shell_on_reconnect(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(ApiClient, "get_my_profile", lambda self: {"role": "member"})

    vm = _isolated_viewmodel(tmp_path)
    server = vm.add_server(host="192.168.1.10", port=8000)
    identity_vm = _isolated_identity_viewmodel(tmp_path)
    identity_vm.set_identity(server.id, 7, "Bob")

    window = _make_window(tmp_path, server_list_vm=vm, identity_vm=identity_vm)
    qtbot.addWidget(window)
    tile = window._saved_tiles_layout.itemAt(0).widget()
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert window._app_shell is not None
    assert window.api_client.user_id == 7


def test_switch_account_returns_to_connect_window(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(ApiClient, "get_my_profile", lambda self: {"role": "member"})

    vm = _isolated_viewmodel(tmp_path)
    server = vm.add_server(host="192.168.1.10", port=8000)
    identity_vm = _isolated_identity_viewmodel(tmp_path)
    identity_vm.set_identity(server.id, 7, "Bob")

    window = _make_window(tmp_path, server_list_vm=vm, identity_vm=identity_vm)
    qtbot.addWidget(window)
    tile = window._saved_tiles_layout.itemAt(0).widget()
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    window._on_switch_account()

    assert window._app_shell is None
    assert window.isHidden() is False


def test_admin_role_grants_server_settings_nav(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(
        ApiClient, "get_my_profile", lambda self: {"id": 1, "name": "Alice", "role": "admin"}
    )

    def _fake_exec(self):
        self.result_user_id = 1
        self.result_user_name = "Alice"
        return AuthDialog.DialogCode.Accepted

    monkeypatch.setattr(AuthDialog, "exec", _fake_exec)

    vm = _isolated_viewmodel(tmp_path)
    vm.add_server(host="192.168.1.10", port=8000)

    window = _make_window(tmp_path, server_list_vm=vm)
    qtbot.addWidget(window)
    tile = window._saved_tiles_layout.itemAt(0).widget()
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    nav_items = [
        window._app_shell.nav_list.item(i).text() for i in range(window._app_shell.nav_list.count())
    ]
    assert "Server Settings" in nav_items


def test_profile_lookup_failure_defaults_to_non_admin(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])

    def _fail_profile(self):
        import httpx

        raise httpx.ConnectError("refused")

    monkeypatch.setattr(ApiClient, "get_my_profile", _fail_profile)

    def _fake_exec(self):
        self.result_user_id = 1
        self.result_user_name = "Alice"
        return AuthDialog.DialogCode.Accepted

    monkeypatch.setattr(AuthDialog, "exec", _fake_exec)

    vm = _isolated_viewmodel(tmp_path)
    vm.add_server(host="192.168.1.10", port=8000)

    window = _make_window(tmp_path, server_list_vm=vm)
    qtbot.addWidget(window)
    tile = window._saved_tiles_layout.itemAt(0).widget()
    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    nav_items = [
        window._app_shell.nav_list.item(i).text() for i in range(window._app_shell.nav_list.count())
    ]
    assert "Server Settings" not in nav_items


def test_empty_sections_show_placeholder_text(qtbot, tmp_path) -> None:
    window = _make_window(tmp_path)
    qtbot.addWidget(window)

    assert window._discovered_tiles_layout.count() == 2  # placeholder + stretch
    assert window._saved_tiles_layout.count() == 2


def test_discovered_server_renders_a_tile(qtbot, tmp_path) -> None:
    listener = StubDiscoveryListener()
    listener._servers = [
        DiscoveredServer(instance_id="x", name="Kairos Server", host="192.168.1.5", port=8000)
    ]

    window = _make_window(tmp_path, discovery_listener=listener)
    qtbot.addWidget(window)
    listener.server_discovered.emit(listener._servers[0])

    assert window._discovered_tiles_layout.count() == 2  # one tile + stretch
    tile = window._discovered_tiles_layout.itemAt(0).widget()
    assert tile.name_label.text() == "Kairos Server"
    assert "192.168.1.5:8000" in tile.subtitle_label.text()


def test_clicking_discovered_tile_auto_saves_and_connects(qtbot, monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )

    def _fake_exec(self):
        return AuthDialog.DialogCode.Rejected

    monkeypatch.setattr(AuthDialog, "exec", _fake_exec)

    vm = _isolated_viewmodel(tmp_path)
    listener = StubDiscoveryListener()
    discovered = DiscoveredServer(
        instance_id="x", name="Kairos Server", host="192.168.1.5", port=8000
    )
    listener._servers = [discovered]

    window = _make_window(tmp_path, server_list_vm=vm, discovery_listener=listener)
    qtbot.addWidget(window)

    assert vm.list_servers() == []  # nothing saved yet

    window._on_discovered_tile_clicked(discovered)

    saved = vm.list_servers()
    assert len(saved) == 1
    assert saved[0].host == "192.168.1.5"
    assert saved[0].port == 8000
    assert window.status_label.text().startswith("Connected to")


def test_clicking_discovered_tile_twice_does_not_duplicate_saved_entry(
    qtbot, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(ApiClient, "health", lambda self: {"status": "ok"})
    monkeypatch.setattr(
        ApiClient, "get_server_info", lambda self: {"display_name": "Kairos Server"}
    )

    def _fake_exec(self):
        return AuthDialog.DialogCode.Rejected

    monkeypatch.setattr(AuthDialog, "exec", _fake_exec)

    vm = _isolated_viewmodel(tmp_path)
    discovered = DiscoveredServer(
        instance_id="x", name="Kairos Server", host="192.168.1.5", port=8000
    )
    window = _make_window(tmp_path, server_list_vm=vm)
    qtbot.addWidget(window)

    window._on_discovered_tile_clicked(discovered)
    window._on_discovered_tile_clicked(discovered)

    assert len(vm.list_servers()) == 1


def test_remove_saved_server_clears_it(qtbot, tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)
    vm.add_server(host="192.168.1.10", port=8000)

    window = _make_window(tmp_path, server_list_vm=vm)
    qtbot.addWidget(window)
    server = vm.list_servers()[0]

    window._on_remove_saved_server(server)

    assert vm.list_servers() == []


def test_closing_window_stops_discovery_listener(qtbot, tmp_path) -> None:
    stopped = []
    listener = StubDiscoveryListener()
    listener.stop = lambda: stopped.append(True)

    window = _make_window(tmp_path, discovery_listener=listener)
    qtbot.addWidget(window)

    window.close()

    assert stopped == [True]
