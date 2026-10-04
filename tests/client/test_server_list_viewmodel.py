from PySide6.QtCore import QSettings

from client.viewmodels.server_list_viewmodel import ServerListViewModel


def _isolated_viewmodel(tmp_path) -> ServerListViewModel:
    ini_path = str(tmp_path / "test_settings.ini")
    settings = QSettings(ini_path, QSettings.Format.IniFormat)
    return ServerListViewModel(settings=settings)


def test_add_and_persist_known_server(tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)

    server = vm.add_server(host="192.168.1.10", port=8000, display_name_cache="Alice's Laptop")

    # A fresh viewmodel instance re-reads from the same backing file, proving the
    # write actually persisted rather than just living in memory.
    reloaded = _isolated_viewmodel(tmp_path)
    servers = reloaded.list_servers()
    assert len(servers) == 1
    assert servers[0].id == server.id
    assert servers[0].host == "192.168.1.10"
    assert servers[0].port == 8000
    assert servers[0].label == "Alice's Laptop"


def test_nickname_overrides_display_name_in_label(tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)

    server = vm.add_server(
        host="10.0.0.5", port=8000, display_name_cache="Server Name", nickname="Kaleb's PC"
    )

    assert server.label == "Kaleb's PC"


def test_mark_connected_sets_last_used(tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)
    server = vm.add_server(host="10.0.0.5", port=8000)

    assert vm.get_last_used_id() is None

    vm.mark_connected(server.id)

    assert vm.get_last_used_id() == server.id
    assert vm.list_servers()[0].last_connected_at is not None


def test_remove_server_clears_last_used(tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)
    server = vm.add_server(host="10.0.0.5", port=8000)
    vm.mark_connected(server.id)

    vm.remove_server(server.id)

    assert vm.list_servers() == []
    assert vm.get_last_used_id() is None
