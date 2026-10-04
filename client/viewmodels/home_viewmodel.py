"""The signed-in home screen, without any widgets: who is signed in, sending a
test message (optionally with a file, image or audio attachment), and signing
out (here or everywhere).
"""

from PySide6.QtCore import QObject, Signal

from client.viewmodels.attachments import AttachmentKind, PendingAttachment
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.login_viewmodel import Session
from shared.roles import ROLE_DISPLAY_NAMES


class HomeViewModel(QObject):
    """State and actions for the home screen's header and Messages tab. The view shows what this
    says through the signals below.
    """

    #: A message was accepted by the server; carries the text that was sent.
    message_sent = Signal(str)
    #: True while a message is on its way; the view locks the message box.
    sending_changed = Signal(bool)
    #: A send failed; carries the text so the view can give it back.
    send_failed = Signal(str)
    #: The attachment waiting to be sent changed: a PendingAttachment, or None.
    attachment_changed = Signal(object)
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
        self._attachment: PendingAttachment | None = None

    @property
    def display_name(self) -> str:
        """E.g. "Nick (Project Lead)"."""
        user = self.session.user
        role = ROLE_DISPLAY_NAMES.get(user["role"], user["role"])
        return f"{user['name']} ({role})"

    @property
    def server_url(self) -> str:
        """The address of the server this session is signed in to."""
        return self.session.client.base_url

    @property
    def sending(self) -> bool:
        """True while a message is on its way."""
        return self._sending

    @property
    def signing_out(self) -> bool:
        """True once sign-out has started."""
        return self._signing_out

    @property
    def attachment(self) -> PendingAttachment | None:
        """The file waiting to be sent with the next message, or None."""
        return self._attachment

    def attach(self, path: str, kind: AttachmentKind) -> None:
        """Hold ``path`` as the attachment for the next send (replacing any)."""
        try:
            attachment = PendingAttachment.from_path(path, kind)
        except ValueError as exc:
            self.error_changed.emit(str(exc))
            return
        self.error_changed.emit("")
        self._attachment = attachment
        self.attachment_changed.emit(attachment)

    def clear_attachment(self) -> None:
        """Drop the waiting attachment (the chip's X button)."""
        if self._attachment is not None:
            self._attachment = None
            self.attachment_changed.emit(None)

    def send_message(self, text: str) -> None:
        """Send a connectivity-test message under the signed-in user's name.

        Ignored while a previous message is still on its way. Without this,
        pressing Enter again during a slow send posted the same message twice.
        """
        content = text.strip()
        # MERGE-CRITICAL: keep this guard. If lost, pressing Enter twice
        # sends the message twice. Guarded by: tests/client/test_message_sending.py.
        if self._signing_out or self._sending:
            return
        if self._attachment is not None:
            self._send_with_attachment(content, self._attachment)
            return
        if not content:
            return
        self.error_changed.emit("")
        self._set_sending(True)
        self._runner.run(
            lambda: self.session.client.send_message(content),
            on_success=lambda _body: self._sent(content),
            on_error=lambda message: self._failed(content, message),
        )

    def _send_with_attachment(self, content: str, attachment: PendingAttachment) -> None:
        """Send a message that carries a file, image or audio clip.

        TODO(attachments): connect this to the server. Nothing is uploaded or
        stored yet -- this only tells the user so, and keeps their text and
        attachment so nothing is lost. To finish it:

        1. Upload the file in the background, like ``send_message`` does:
               self._set_sending(True)
               self._runner.run(
                   lambda: self.session.client.upload_attachment(
                       attachment.path, attachment.kind, content
                   ),
                   on_success=lambda _body: self._attachment_sent(content, attachment),
                   on_error=lambda message: self._failed(content, message),
               )
           ``ApiClient.upload_attachment`` is stubbed in
           client/api_client/client.py (marked TODO(attachments)).
        2. Write ``_attachment_sent(content, attachment)``: call
           ``self._set_sending(False)`` and ``self.clear_attachment()``, then
           emit ``message_sent`` with e.g. f"{content} [{attachment.name}]" so
           the message log shows it.
        3. Server side -- also marked TODO(attachments): a route in
           server/api/messages.py, storage in server/services/message_service.py,
           columns in server/models/message.py (needs an Alembic migration),
           and the 1 MB request limit in server/api/protection.py.
        """
        self.error_changed.emit(
            f"Attachments aren't connected to the server yet - {attachment.name} wasn't sent."
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
        """Run ``call`` (logout or logout-everywhere) once, then emit ``signed_out`` whatever
        happened.
        """
        if self._signing_out:
            return
        self._signing_out = True
        self._runner.run(
            call,
            on_success=lambda _none: self.signed_out.emit(),
            on_error=lambda _message: self.signed_out.emit(),
        )

    def _sent(self, content: str) -> None:
        """The server accepted the message: unlock the box and log it."""
        self._set_sending(False)
        self.message_sent.emit(content)

    def _failed(self, content: str, message: str) -> None:
        """The send failed: unlock the box, give the text back and show why."""
        self._set_sending(False)
        self.error_changed.emit(f"Send failed: {message}")
        self.send_failed.emit(content)

    def _set_sending(self, sending: bool) -> None:
        """Record whether a send is in flight and tell the view."""
        self._sending = sending
        self.sending_changed.emit(sending)
