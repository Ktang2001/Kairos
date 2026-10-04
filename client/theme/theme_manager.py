from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

RESOURCES_DIR = Path(__file__).resolve().parent.parent / "resources"
VALID_MODES = ("auto", "light", "dark")
_THEME_MODE_KEY = "ui/theme_mode"


class ThemeManager(QObject):
    """Resolves and applies the app's Light/Dark/Auto theme as one global QSS
    stylesheet (client/resources/{light,dark}.qss) rather than per-widget styling.
    Persists the user's preference via the same QSettings org/app already used by
    the other viewmodels (see client/viewmodels/server_list_viewmodel.py).
    """

    theme_changed = Signal(str)  # emits the resolved scheme: "light" or "dark"

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self._settings = settings or QSettings("Kairos", "KairosClient")
        self._auto_connected = False

    def get_mode(self) -> str:
        mode = self._settings.value(_THEME_MODE_KEY, "auto")
        return mode if mode in VALID_MODES else "auto"

    def set_mode(self, mode: str) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"invalid theme mode: {mode!r}")
        self._settings.setValue(_THEME_MODE_KEY, mode)
        self.apply()

    def resolve_effective_scheme(self) -> str:
        """What to actually render right now - resolves "auto" against the live
        OS setting. Falls back to light for both an unknown OS scheme (common on
        Linux desktops whose portal doesn't report one) and a missing GUI app
        (e.g. construction before QApplication exists)."""
        if self.get_mode() != "auto":
            return self.get_mode()

        app = QGuiApplication.instance()
        if app is None:
            return "light"
        if app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
            return "dark"
        return "light"

    def apply(self) -> None:
        scheme = self.resolve_effective_scheme()
        qss_path = RESOURCES_DIR / f"{scheme}.qss"
        stylesheet = qss_path.read_text() if qss_path.exists() else ""

        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        self.theme_changed.emit(scheme)

        # Connected once, lazily - the handler itself checks get_mode() == "auto"
        # each time, so staying connected while in a non-auto mode is harmless.
        if not self._auto_connected:
            gui_app = QGuiApplication.instance()
            if gui_app is not None:
                gui_app.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
                self._auto_connected = True

    def _on_system_scheme_changed(self, _scheme: Qt.ColorScheme) -> None:
        if self.get_mode() == "auto":
            self.apply()
