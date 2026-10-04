"""The desktop client's entry point (``python -m client.main``).

Opens the connect window (choose or discover a server, sign in), which opens
the main app window once signed in.
"""

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from client.main_thread_gc import MainThreadGarbageCollector
from client.theme import ThemeManager
from client.views.connect_window import ConnectWindow

ICON_PATH = Path(__file__).resolve().parent / "resources" / "kairos.svg"
DESKTOP_FILE_ID = "kairos-client"


def main() -> None:
    """Start the app: main-thread garbage collection first, then the connect window."""
    app = QApplication(sys.argv)
    # MERGE-CRITICAL: create this right after QApplication and before any
    # window. If lost: the app crashes now and then with an access violation
    # (Python's garbage collector destroying Qt objects on a background thread).
    # See client/main_thread_gc.py. Guarded by: tests/client/test_rare_paths.py.
    _collector = MainThreadGarbageCollector(app)
    app.setWindowIcon(QIcon(str(ICON_PATH)))
    # setWindowIcon() alone only covers the title bar - Wayland taskbars look up
    # the icon via the window's app_id matching an installed .desktop file's
    # Icon= entry instead (see scripts/install_linux_desktop_entries.py).
    app.setDesktopFileName(DESKTOP_FILE_ID)

    theme_manager = ThemeManager()
    theme_manager.apply()

    window = ConnectWindow(theme_manager=theme_manager)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
