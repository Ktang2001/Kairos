import sys

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget

from client.settings import ClientSettings
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import LoginViewModel, Session
from client.views.home_view import HomeView
from client.views.login_view import LoginView

#: How long closing the window may wait to tell the server the session is over.
#: Short, because a host that has gone away would otherwise hold up closing.
LOGOUT_ON_CLOSE_TIMEOUT = 2.0


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

        self.stack = QStackedWidget()
        self.stack.addWidget(self.login_view)
        self.setCentralWidget(self.stack)

        self.login_viewmodel.signed_in.connect(self._show_home)

    def _show_home(self, session: Session) -> None:
        self.home_viewmodel = HomeViewModel(session, parent=self)
        self.home_view = HomeView(self.home_viewmodel)
        self.home_viewmodel.signed_out.connect(self._show_login)
        self.stack.addWidget(self.home_view)
        self.stack.setCurrentWidget(self.home_view)
        self.setWindowTitle(f"Kairos — {session.user['name']}")

    def _show_login(self) -> None:
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
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
