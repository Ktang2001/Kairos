"""The signed-in home screen, without any widgets: who is signed in, sending a
test message, and signing out (here or everywhere).
"""

from PySide6.QtCore import QObject, Signal

from client.viewmodels.background import BackgroundRunner
from client.viewmodels.login_viewmodel import Session
from shared.roles import ROLE_DISPLAY_NAMES


class HomeViewModel(QObject):
    #: A message was accepted by the server; carries the text that was sent.
    message_sent = Signal(str)
    #: True while a message is on its way; the view locks the message box.
    sending_changed = Signal(bool)
    #: A send failed; carries the text so the view can give it back.
    send_failed = Signal(str)
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
        self._sending = False

    @property
    def display_name(self) -> str:
        """E.g. "Nick (Project Lead)"."""
        user = self.session.user
        role = ROLE_DISPLAY_NAMES.get(user["role"], user["role"])
        return f"{user['name']} ({role})"

    @property
    def server_url(self) -> str:
        return self.session.client.base_url

    @property
    def sending(self) -> bool:
        return self._sending

    @property
    def signing_out(self) -> bool:
        return self._signing_out

    def send_message(self, text: str) -> None:
        """Send a connectivity-test message under the signed-in user's name.

        Ignored while a previous message is still on its way. Without this,
        pressing Enter again during a slow send posted the same message twice.
        """
        content = text.strip()
        if not content or self._signing_out or self._sending:
            return
        self.error_changed.emit("")
        self._set_sending(True)
        self._runner.run(
            lambda: self.session.client.send_message(content),
            on_success=lambda _body: self._sent(content),
            on_error=lambda message: self._failed(content, message),
        )

    def sign_out(self) -> None:
        """Revoke this session and return to the login screen.

        ``ApiClient.logout`` never raises, so this always ends in
        ``signed_out`` -- even if the host is gone.
        """
        self._sign_out_with(self.session.client.logout)

    def sign_out_everywhere(self) -> None:
        """Revoke every session of this account (all devices), then return to
        the login screen. Never fails, like ``sign_out``.
        """
        self._sign_out_with(self.session.client.logout_everywhere)

    def _sign_out_with(self, call) -> None:
        if self._signing_out:
            return
        self._signing_out = True
        self._runner.run(
            call,
            on_success=lambda _none: self.signed_out.emit(),
            on_error=lambda _message: self.signed_out.emit(),
        )

    def _sent(self, content: str) -> None:
        self._set_sending(False)
        self.message_sent.emit(content)

    def _failed(self, content: str, message: str) -> None:
        self._set_sending(False)
        self.error_changed.emit(f"Send failed: {message}")
        self.send_failed.emit(content)

    def _set_sending(self, sending: bool) -> None:
        self._sending = sending
        self.sending_changed.emit(sending)
