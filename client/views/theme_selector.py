from PySide6.QtWidgets import QComboBox, QWidget

from client.theme import ThemeManager

_LABELS = {"auto": "Auto", "light": "Light", "dark": "Dark"}
_MODES_BY_LABEL = {label: mode for mode, label in _LABELS.items()}


class ThemeSelector(QComboBox):
    """A small Auto/Light/Dark dropdown bound to a ThemeManager.

    Used in both ConnectWindow and AppShell's header - the user can be on either
    screen when they want to change it, and both read/write the same ThemeManager
    (backed by QSettings), so no sync code is needed between the two.
    """

    def __init__(self, theme_manager: ThemeManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._theme_manager = theme_manager
        self.addItems(list(_LABELS.values()))
        self.setCurrentText(_LABELS[theme_manager.get_mode()])
        self.currentTextChanged.connect(self._on_changed)

    def _on_changed(self, label: str) -> None:
        self._theme_manager.set_mode(_MODES_BY_LABEL[label])
