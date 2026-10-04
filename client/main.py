"""The desktop client's main window and entry point (``python -m client.main``).

``MainWindow`` holds two screens in a stack: the login screen, then the home screen once signed in.
It switches between them on sign-in, sign-out and session expiry, and signs out on the server when
the window closes.
"""

import sys

from PySide6.QtCore import Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from client.main_thread_gc import MainThreadGarbageCollector
from client.settings import ClientSettings
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import LoginViewModel, Session
from client.viewmodels.session_events import SessionEvents
from client.views.home_view import HomeView
from client.views.login_view import LoginView

#: How long closing the window may wait to tell the server the session is over.
#: Short, because a host that has gone away would otherwise hold up closing.
LOGOUT_ON_CLOSE_TIMEOUT = 2.0

#: Minimum window size once signed in (width, height).
SIGNED_IN_SIZE = (820, 560)

SESSION_EXPIRED_MESSAGE = "Your session has expired. Please sign in again."


class MainWindow(QMainWindow):
    """Shows the login screen, then the home screen once signed in."""

    def __init__(self, settings: ClientSettings | None = None) -> None:
        super().__init__()
        self.setWindowTitle("Kairos")
        self.resize(480, 420)

        self.settings = settings or ClientSettings()
        self.login_viewmodel = LoginViewModel(parent=self)
        self.login_view = LoginView(self.login_viewmodel, self.settings)
        self.home_viewmodel: HomeViewModel | None = None
        self.home_view: HomeView | None = None
        self.session_events: SessionEvents | None = None

        self.stack = QStackedWidget()
        self.stack.addWidget(self.login_view)
        self.setCentralWidget(self.stack)

        self.login_viewmodel.signed_in.connect(self._show_home)

    def _show_home(self, session: Session) -> None:
        """Signed in: build the home screen for this session, watch its connection, and show it."""
        self.session_events = SessionEvents(self)
        self.session_events.attach(session.client)
        self.session_events.expired.connect(self._on_session_expired)
        self.home_viewmodel = HomeViewModel(session, parent=self)
        self.home_view = HomeView(self.home_viewmodel, events=self.session_events)
        self.home_viewmodel.signed_out.connect(self._show_login)
        self.stack.addWidget(self.home_view)
        self.stack.setCurrentWidget(self.home_view)
        self.setWindowTitle(f"Kairos — {session.user['name']}")
        # The Teams screen needs room for its two columns.
        self.resize(max(self.width(), SIGNED_IN_SIZE[0]), max(self.height(), SIGNED_IN_SIZE[1]))
        self.home_view.load()

    @Slot()
    def _on_session_expired(self) -> None:
        """The server stopped accepting this session (it expired, or was ended
        by "sign out everywhere" on another computer). Go back to the login
        screen and say why, with the email already filled in.
        """
        if self.home_viewmodel is None:
            return
        self.home_viewmodel.session.client.token = None  # dead; don't send it again
        self._show_login()
        self.login_view.show_message(SESSION_EXPIRED_MESSAGE)

    def _show_login(self) -> None:
        """Back to the login screen: tear down the home screen and forget the session."""
        if self.session_events is not None and self.home_viewmodel is not None:
            self.session_events.detach(self.home_viewmodel.session.client)
            self.session_events.deleteLater()
        self.session_events = None
        if self.home_view is not None:
            self.stack.removeWidget(self.home_view)
            self.home_view.deleteLater()
        if self.home_viewmodel is not None:
            self.home_viewmodel.deleteLater()
        self.home_view = None
        self.home_viewmodel = None

        self.login_view.reset_after_sign_out()
        self.stack.setCurrentWidget(self.login_view)
        self.setWindowTitle("Kairos")

    def closeEvent(self, event: QCloseEvent) -> None:
        """Closing while signed in also signs out, so the token stops working
        on the server instead of staying valid for its full 14 days.
        """
        if self.home_viewmodel is not None:
            client = self.home_viewmodel.session.client
            client.timeout = LOGOUT_ON_CLOSE_TIMEOUT
            client.logout()  # never raises
        super().closeEvent(event)


def main() -> None:
    """Start the app: main-thread garbage collection first, then the window."""
    app = QApplication(sys.argv)
    # MERGE-CRITICAL: create this right after QApplication and before any
    # window, in whichever main() survives a merge (e.g. one that opens a
    # different first window). If lost: the app crashes now and then with an
    # access violation (garbage collected on a background thread). See
    # client/main_thread_gc.py. Guarded by: tests/client/test_rare_paths.py.
    _collector = MainThreadGarbageCollector(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
