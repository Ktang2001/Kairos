from PySide6.QtCore import QSettings

from client.viewmodels.identity_viewmodel import IdentityViewModel


def _isolated_viewmodel(tmp_path) -> IdentityViewModel:
    ini_path = str(tmp_path / "test_settings.ini")
    return IdentityViewModel(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def test_set_and_reload_cached_identity(tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)

    vm.set_identity("server-1", 7, "Alice")

    reloaded = _isolated_viewmodel(tmp_path)
    cached = reloaded.load_cached_identity("server-1")

    assert cached == (7, "Alice")
    assert reloaded.user_id == 7
    assert reloaded.user_name == "Alice"


def test_no_cached_identity_for_unknown_server(tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)

    assert vm.load_cached_identity("never-seen") is None


def test_identities_are_scoped_per_server(tmp_path) -> None:
    vm = _isolated_viewmodel(tmp_path)
    vm.set_identity("server-1", 7, "Alice")
    vm.set_identity("server-2", 9, "Bob")

    assert vm.load_cached_identity("server-1") == (7, "Alice")
    assert vm.load_cached_identity("server-2") == (9, "Bob")
