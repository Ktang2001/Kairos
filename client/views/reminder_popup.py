"""Showing a meeting reminder: a small pop-up with Join, plus a desktop notice.

The pop-up stays on top of other windows and doesn't block Kairos. The
desktop notice shows even when Kairos is minimised: through the system tray
where the desktop has one (Windows, KDE), otherwise -- GNOME has no tray by
default -- through ``notify-send``, which hands it to the desktop's own
notification service. Either way the taskbar entry flashes too.
"""

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from client.views.meeting_card import meeting_when
from client.views.widgets import ElidedLabel

#: How long the desktop notice stays up, in milliseconds.
NOTICE_MS = 10_000

#: The app icon, for desktop notices sent through notify-send.
ICON_PATH = Path(__file__).resolve().parent.parent / "resources" / "kairos.svg"


def _start_detached(program: str, arguments: list[str]) -> bool:
    """Start ``program`` without waiting for it; True if it started."""
    result = QProcess.startDetached(program, arguments)
    # Some PySide6 versions return (started, pid), others just started.
    return bool(result[0] if isinstance(result, tuple) else result)


class ReminderPopup(QDialog):
    """ "Stand-up · Starts in 15 minutes" with Join and Dismiss."""

    join_clicked = Signal(int)

    def __init__(self, meeting: dict, message: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Meeting reminder")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.meeting = meeting

        # Titles came from people: plain text (ElidedLabel), never HTML.
        self.title_label = ElidedLabel()
        self.title_label.setStyleSheet("font-weight: 600; font-size: 12pt;")
        self.message_label = QLabel()
        self.message_label.setTextFormat(Qt.TextFormat.PlainText)
        self.when_label = ElidedLabel()
        self.when_label.setProperty("muted", True)

        self.join_button = QPushButton("Join")
        self.join_button.setProperty("primary", True)
        self.dismiss_button = QPushButton("Dismiss")
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(self.dismiss_button)
        buttons.addWidget(self.join_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.message_label)
        layout.addWidget(self.when_label)
        layout.addLayout(buttons)
        self.setMinimumWidth(360)

        self.join_button.clicked.connect(self._join)
        self.dismiss_button.clicked.connect(self.close)
        self.show_reminder(meeting, message)

    def show_reminder(self, meeting: dict, message: str) -> None:
        """Show (newer details of) the reminder."""
        self.meeting = meeting
        self.title_label.set_full_text(meeting["title"])
        self.message_label.setText(message)
        self.when_label.set_full_text(meeting_when(meeting))

    def _join(self) -> None:
        self.join_clicked.emit(self.meeting["id"])
        self.close()


class ReminderNotifier(QObject):
    """Shows reminders: one pop-up per meeting, and a desktop notice each time."""

    join_clicked = Signal(int)

    def __init__(self, window: QWidget, icon: QIcon | None = None) -> None:
        super().__init__(window)
        self._window = window
        #: Open pop-ups by meeting id: a second reminder updates the first
        #: rather than stacking another window.
        self.popups: dict[int, ReminderPopup] = {}
        self._tray: QSystemTrayIcon | None = None
        #: notify-send, on a Linux desktop without a tray; None elsewhere.
        self.notify_send = shutil.which("notify-send") if sys.platform.startswith("linux") else None
        #: Starts a program without waiting for it. Replaced in tests.
        self.run_command: Callable[[str, list[str]], bool] = _start_detached
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray = QSystemTrayIcon(icon or QApplication.windowIcon(), self)
            self._tray.setToolTip("Kairos")
            self._tray.messageClicked.connect(self._bring_window_forward)

    def notify(self, meeting: dict, message: str) -> None:
        """Show a reminder for ``meeting``."""
        popup = self.popups.get(meeting["id"])
        if popup is None:
            popup = ReminderPopup(meeting, message, self._window)
            popup.join_clicked.connect(self.join_clicked)
            popup.destroyed.connect(lambda *_args, mid=meeting["id"]: self.popups.pop(mid, None))
            self.popups[meeting["id"]] = popup
        else:
            popup.show_reminder(meeting, message)
        popup.show()
        popup.raise_()

        body = f"{message} · {meeting_when(meeting)}"
        if self._tray is not None and self._tray.supportsMessages():
            self._tray.show()
            self._tray.showMessage(
                meeting["title"], body, QSystemTrayIcon.MessageIcon.Information, NOTICE_MS
            )
        elif self.notify_send:
            # Arguments, not a shell line: a title can't run anything.
            self.run_command(
                self.notify_send,
                [
                    "--app-name=Kairos",
                    f"--icon={ICON_PATH}",
                    f"--expire-time={NOTICE_MS}",
                    "--",
                    meeting["title"],
                    body,
                ],
            )
        QApplication.alert(self._window)

    def close_all(self) -> None:
        """Close every pop-up and remove the tray icon (signing out)."""
        for popup in list(self.popups.values()):
            popup.close()
        if self._tray is not None:
            self._tray.hide()

    def _bring_window_forward(self) -> None:
        self._window.showNormal()
        self._window.raise_()
        self._window.activateWindow()
