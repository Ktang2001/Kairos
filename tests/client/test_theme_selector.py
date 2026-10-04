from PySide6.QtCore import QSettings

from client.theme.theme_manager import ThemeManager
from client.views.theme_selector import ThemeSelector


def _isolated_theme_manager(tmp_path) -> ThemeManager:
    ini_path = str(tmp_path / "test_theme.ini")
    return ThemeManager(settings=QSettings(ini_path, QSettings.Format.IniFormat))


def test_initial_selection_matches_current_mode(qtbot, tmp_path) -> None:
    tm = _isolated_theme_manager(tmp_path)
    tm.set_mode("dark")

    selector = ThemeSelector(tm)
    qtbot.addWidget(selector)

    assert selector.currentText() == "Dark"


def test_changing_selection_updates_theme_manager(qtbot, tmp_path) -> None:
    tm = _isolated_theme_manager(tmp_path)
    selector = ThemeSelector(tm)
    qtbot.addWidget(selector)

    selector.setCurrentText("Light")

    assert tm.get_mode() == "light"
