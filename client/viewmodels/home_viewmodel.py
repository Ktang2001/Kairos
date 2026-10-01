"""The signed-in home screen, without any widgets: who is signed in, sending a
test message, and signing out.
"""

from PySide6.QtCore import QObject, Signal

from client.viewmodels.background import BackgroundRunner
from client.viewmodels.login_viewmodel import Session
from shared.roles import ROLE_DISPLAY_NAMES


class HomeViewModel(QObject):
    #: A message was accepted by the server; carries the text that was sent.
    message_sent = Signal(str)
    #: The message to show, or "" to clear it.
    error_changed = Signal(str)
    #: Sign-out finished; the window should go back to the login screen.
    signed_out = Signal()

    def __init__(
        self,
        session: Session,
        runner: BackgroundRunner | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._runner = runner or BackgroundRunner(self)
        self._signing_out = False

    @property
    def display_name(self) -> str:
        """E.g. "Nick (Project Lead)"."""
        user = self.session.user
        role = ROLE_DISPLAY_NAMES.get(user["role"], user["role"])
        return f"{user['name']} ({role})"

    @property
    def server_url(self) -> str:
        return self.session.client.base_url

    def send_message(self, text: str) -> None:
        """Send a connectivity-test message under the signed-in user's name."""
        content = text.strip()
        if not content or self._signing_out:
            return
        self.error_changed.emit("")
        self._runner.run(
            lambda: self.session.client.send_message(content),
            on_success=lambda _body: self.message_sent.emit(content),
            on_error=lambda message: self.error_changed.emit(f"Send failed: {message}"),
        )

    def sign_out(self) -> None:
        """Revoke the session and return to the login screen.

        ``ApiClient.logout`` never raises, so this always ends in
        ``signed_out`` -- even if the host is gone.
        """
        if self._signing_out:
            return
        self._signing_out = True
        self._runner.run(
            self.session.client.logout,
            on_success=lambda _none: self.signed_out.emit(),
            on_error=lambda _message: self.signed_out.emit(),
        )
