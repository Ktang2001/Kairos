"""Sign-in and account creation, without any widgets.

The view hands over what was typed; this module checks it, talks to the
server on a background thread, and reports back through signals. Keeping it
widget-free means every rule here can be tested without clicking anything.
"""

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from client.api_client import ApiClient, ApiError
from client.viewmodels.background import BackgroundRunner
from shared.account_rules import (
    EMAIL_PATTERN,
    MAX_EMAIL_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PASSWORD_LENGTH,
    MIN_PASSWORD_LENGTH,
    password_problem,
)


@dataclass
class Session:
    """A signed-in user: the client holding their token, and who they are."""

    client: ApiClient
    #: ``{"id", "name", "email", "role"}`` as returned by the server.
    user: dict


def _check_email(email: str) -> str | None:
    if not email:
        return "Enter your email."
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.match(email):
        return "That doesn't look like an email address."
    return None


def validate_sign_in(email: str, password: str) -> str | None:
    """Return a message for the first problem with the form, or None if it is fine."""
    if problem := _check_email(email.strip()):
        return problem
    if not password:
        return "Enter your password."
    return None


def validate_registration(name: str, email: str, password: str, confirm: str) -> str | None:
    """Return a message for the first problem with the form, or None if it is fine.

    Mirrors the server's rules (``shared.account_rules``) so the user hears
    about a short password immediately rather than after a round trip.
    """
    name = name.strip()
    if not name:
        return "Enter your name."
    if len(name) > MAX_NAME_LENGTH:
        return f"Name must be at most {MAX_NAME_LENGTH} characters."
    if problem := _check_email(email.strip()):
        return problem
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if problem := password_problem(password, email=email, name=name):
        return problem
    if password != confirm:
        return "Passwords don't match."
    return None


class LoginViewModel(QObject):
    #: True while a request is in flight; the view locks the form.
    busy_changed = Signal(bool)
    #: The message to show, or "" to clear it.
    error_changed = Signal(str)
    #: Emitted with a ``Session`` once the server accepts the user.
    signed_in = Signal(object)

    def __init__(
        self,
        runner: BackgroundRunner | None = None,
        client_factory: Callable[[str], ApiClient] = ApiClient,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._runner = runner or BackgroundRunner(self)
        self._client_factory = client_factory
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    def clear_error(self) -> None:
        self.error_changed.emit("")

    def sign_in(self, server: str, email: str, password: str) -> None:
        problem = validate_sign_in(email, password)
        email = email.strip()
        self._submit(server, problem, lambda client: client.login(email, password))

    def create_account(
        self, server: str, name: str, email: str, password: str, confirm: str
    ) -> None:
        problem = validate_registration(name, email, password, confirm)
        name, email = name.strip(), email.strip()
        self._submit(server, problem, lambda client: client.register(name, email, password))

    def _submit(self, server: str, problem: str | None, call: Callable[[ApiClient], dict]) -> None:
        # A second click (or Enter) while the first request is still running
        # is ignored rather than sent again.
        if self._busy:
            return

        try:
            client = self._client_factory(server)
        except ApiError as exc:
            self.error_changed.emit(exc.message)
            return
        if problem:
            self.error_changed.emit(problem)
            return

        self.error_changed.emit("")
        self._set_busy(True)
        self._runner.run(
            lambda: call(client),
            on_success=lambda user: self._succeeded(Session(client=client, user=user)),
            on_error=self._failed,
        )

    def _succeeded(self, session: Session) -> None:
        self._set_busy(False)
        self.signed_in.emit(session)

    def _failed(self, message: str) -> None:
        self._set_busy(False)
        self.error_changed.emit(message)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.busy_changed.emit(busy)
