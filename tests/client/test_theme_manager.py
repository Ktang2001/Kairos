from PySide6.QtCore import QSettings, Qt

from client.theme.theme_manager import ThemeManager


def _isolated_theme_manager(tmp_path) -> ThemeManager:
    ini_path = str(tmp_path / "test_theme.ini")
    return ThemeManager(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def test_defaults_to_auto(tmp_path) -> None:
    tm = _isolated_theme_manager(tmp_path)

    assert tm.get_mode() == "auto"


def test_set_mode_persists(tmp_path) -> None:
    tm = _isolated_theme_manager(tmp_path)

    tm.set_mode("dark")

    reloaded = _isolated_theme_manager(tmp_path)
    assert reloaded.get_mode() == "dark"


def test_set_mode_rejects_invalid_value(tmp_path) -> None:
    tm = _isolated_theme_manager(tmp_path)

    try:
        tm.set_mode("purple")
        raised = False
    except ValueError:
        raised = True

    assert raised


def test_resolve_effective_scheme_explicit_modes(tmp_path) -> None:
    tm = _isolated_theme_manager(tmp_path)

    tm.set_mode("dark")
    assert tm.resolve_effective_scheme() == "dark"

    tm.set_mode("light")
    assert tm.resolve_effective_scheme() == "light"


def test_resolve_effective_scheme_auto_follows_system(tmp_path, monkeypatch, qapp) -> None:
    tm = _isolated_theme_manager(tmp_path)
    assert tm.get_mode() == "auto"

    monkeypatch.setattr(type(qapp.styleHints()), "colorScheme", lambda self: Qt.ColorScheme.Dark)
    assert tm.resolve_effective_scheme() == "dark"

    monkeypatch.setattr(type(qapp.styleHints()), "colorScheme", lambda self: Qt.ColorScheme.Unknown)
    assert tm.resolve_effective_scheme() == "light"


def test_apply_sets_global_stylesheet(tmp_path, qapp) -> None:
    tm = _isolated_theme_manager(tmp_path)
    tm.set_mode("dark")

    tm.apply()

    assert "QPushButton" in qapp.styleSheet()


def test_theme_changed_signal_emits_resolved_scheme(tmp_path, qtbot) -> None:
    tm = _isolated_theme_manager(tmp_path)
    tm.set_mode("light")

    with qtbot.waitSignal(tm.theme_changed, timeout=1000) as blocker:
        tm.apply()

    assert blocker.args == ["light"]
