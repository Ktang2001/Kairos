"""The sign-in / create-account screen.

Display and input only: every rule lives in ``LoginViewModel``. One window
with two pages (sign in, create account) that share the server field and the
error line, so switching pages keeps the address you typed.

The error line clears as soon as the user edits any field, and the cursor
starts in the first field that still needs typing.
"""

import os

from PySide6.QtCore import Qt
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api_client.client import DEFAULT_BASE_URL
from client.settings import ClientSettings
from client.viewmodels.login_viewmodel import LoginViewModel, Session
from client.views.widgets import ErrorLabel
from shared.account_rules import MAX_EMAIL_LENGTH, MAX_NAME_LENGTH

SIGN_IN_PAGE = 0
REGISTER_PAGE = 1

#: The form stops growing past this width and stays centred, so on a
#: maximised window the fields are not stretched across the whole screen.
MAX_FORM_WIDTH = 520


def _password_field() -> QLineEdit:
    field = QLineEdit()
    field.setEchoMode(QLineEdit.EchoMode.Password)
    return field


def _form(label_width: int, rows: list[tuple[str, QWidget]]) -> QFormLayout:
    """A form whose label column has a fixed width, so the server field and
    both pages' fields all start at the same x position.
    """
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    for text, field in rows:
        label = QLabel(text)
        label.setFixedWidth(label_width)
        form.addRow(label, field)
    return form


def _link_button(text: str) -> QPushButton:
    button = QPushButton(text)
    button.setFlat(True)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


class LoginView(QWidget):
    def __init__(
        self,
        viewmodel: LoginViewModel,
        settings: ClientSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.viewmodel = viewmodel
        self.settings = settings

        title = QLabel("Kairos")
        title.setStyleSheet("font-size: 22px; font-weight: 600;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.server_input = QLineEdit(
            settings.server_url or os.environ.get("KAIROS_SERVER_URL", DEFAULT_BASE_URL)
        )
        self.server_input.setPlaceholderText("e.g. 192.168.1.5:8000")
        # Wide enough for the longest label on either page.
        label_width = self.fontMetrics().horizontalAdvance("Confirm password") + 12
        server_form = _form(label_width, [("Server", self.server_input)])

        # --- sign-in page
        self.email_input = QLineEdit(settings.last_email or "")
        self.email_input.setPlaceholderText("you@example.com")
        self.email_input.setMaxLength(MAX_EMAIL_LENGTH)
        self.password_input = _password_field()
        self.sign_in_button = QPushButton("Sign in")
        self.sign_in_button.setDefault(True)
        self.show_register_button = _link_button("No account? Create one")

        sign_in_form = _form(
            label_width, [("Email", self.email_input), ("Password", self.password_input)]
        )
        sign_in_page = QWidget()
        sign_in_layout = QVBoxLayout(sign_in_page)
        sign_in_layout.setContentsMargins(0, 0, 0, 0)
        sign_in_layout.addLayout(sign_in_form)
        sign_in_layout.addWidget(self.sign_in_button)
        sign_in_layout.addWidget(self.show_register_button)

        # --- create-account page
        self.name_input = QLineEdit()
        self.name_input.setMaxLength(MAX_NAME_LENGTH)
        self.register_email_input = QLineEdit()
        self.register_email_input.setPlaceholderText("you@example.com")
        self.register_email_input.setMaxLength(MAX_EMAIL_LENGTH)
        self.register_password_input = _password_field()
        self.register_password_input.setPlaceholderText("at least 8 characters")
        self.confirm_input = _password_field()
        self.create_button = QPushButton("Create account")
        self.show_sign_in_button = _link_button("Already have an account? Sign in")

        register_form = _form(
            label_width,
            [
                ("Name", self.name_input),
                ("Email", self.register_email_input),
                ("Password", self.register_password_input),
                ("Confirm password", self.confirm_input),
            ],
        )
        register_page = QWidget()
        register_layout = QVBoxLayout(register_page)
        register_layout.setContentsMargins(0, 0, 0, 0)
        register_layout.addLayout(register_form)
        register_layout.addWidget(self.create_button)
        register_layout.addWidget(self.show_sign_in_button)

        # Both pages sit in the layout and only one is shown at a time. (A
        # QStackedWidget would always be as tall as the taller page, leaving
        # a gap under the shorter sign-in form.)
        self._pages = [sign_in_page, register_page]
        self.current_page = SIGN_IN_PAGE
        self._show_page(SIGN_IN_PAGE)

        self.error_label = ErrorLabel()

        form_column = QWidget()
        form_column.setMaximumWidth(MAX_FORM_WIDTH)
        column = QVBoxLayout(form_column)
        column.setContentsMargins(0, 0, 0, 0)
        column.addWidget(title)
        column.addLayout(server_form)
        column.addWidget(sign_in_page)
        column.addWidget(register_page)
        column.addWidget(self.error_label)

        centred = QHBoxLayout()
        centred.addStretch()
        centred.addWidget(form_column, stretch=1)
        centred.addStretch()

        layout = QVBoxLayout(self)
        layout.addLayout(centred)
        layout.addStretch()

        # --- wiring
        self.sign_in_button.clicked.connect(self.submit_sign_in)
        for field in (self.server_input, self.email_input, self.password_input):
            field.returnPressed.connect(self._submit_current_page)
        self.create_button.clicked.connect(self.submit_registration)
        for field in (
            self.name_input,
            self.register_email_input,
            self.register_password_input,
            self.confirm_input,
        ):
            field.returnPressed.connect(self._submit_current_page)
        self.show_register_button.clicked.connect(self.show_register_page)
        self.show_sign_in_button.clicked.connect(self.show_sign_in_page)
        # textEdited fires only for the user's own typing, not for setText, so
        # filling fields in code never wipes a message the user should see.
        for field in self.findChildren(QLineEdit):
            field.textEdited.connect(self._clear_error_on_edit)
        self._focused_once = False

        viewmodel.busy_changed.connect(self._set_busy)
        viewmodel.error_changed.connect(self._show_error)
        viewmodel.signed_in.connect(self._remember)

        self._inputs = [
            self.server_input,
            self.email_input,
            self.password_input,
            self.name_input,
            self.register_email_input,
            self.register_password_input,
            self.confirm_input,
            self.sign_in_button,
            self.create_button,
            self.show_register_button,
            self.show_sign_in_button,
        ]

    # ------------------------------------------------------------ actions

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not self._focused_once:
            self._focused_once = True
            self.focus_first_empty_field()

    def focus_first_empty_field(self) -> None:
        """Put the cursor where the user needs to type next.

        A returning user has the server and email remembered, so that is the
        password field; a first-time user starts at whichever is empty.
        """
        for field in (self.server_input, self.email_input, self.password_input):
            if not field.text():
                field.setFocus()
                return
        self.password_input.setFocus()

    def submit_sign_in(self) -> None:
        self.viewmodel.sign_in(
            self.server_input.text(), self.email_input.text(), self.password_input.text()
        )

    def submit_registration(self) -> None:
        self.viewmodel.create_account(
            self.server_input.text(),
            self.name_input.text(),
            self.register_email_input.text(),
            self.register_password_input.text(),
            self.confirm_input.text(),
        )

    def _submit_current_page(self) -> None:
        if self.current_page == SIGN_IN_PAGE:
            self.submit_sign_in()
        else:
            self.submit_registration()

    def show_register_page(self) -> None:
        # Carry the email across so it is not typed twice.
        if not self.register_email_input.text():
            self.register_email_input.setText(self.email_input.text())
        self._show_page(REGISTER_PAGE)
        self.viewmodel.clear_error()
        self.name_input.setFocus()

    def show_sign_in_page(self) -> None:
        if self.register_email_input.text():
            self.email_input.setText(self.register_email_input.text())
        self._show_page(SIGN_IN_PAGE)
        self.viewmodel.clear_error()
        self.password_input.setFocus()

    def show_message(self, message: str) -> None:
        """Explain why the user is looking at the login screen (e.g. their
        session expired). Cleared as soon as they start typing.
        """
        self._show_error(message)

    def reset_after_sign_out(self) -> None:
        """Back to a clean sign-in page. Passwords are never left in a field."""
        self._clear_passwords()
        self._show_page(SIGN_IN_PAGE)
        self.viewmodel.clear_error()
        self.password_input.setFocus()

    def _show_page(self, index: int) -> None:
        for i, page in enumerate(self._pages):
            page.setVisible(i == index)
        self.current_page = index

    # ----------------------------------------------------- viewmodel signals

    def _set_busy(self, busy: bool) -> None:
        for widget in self._inputs:
            widget.setEnabled(not busy)
        self.sign_in_button.setText("Signing in…" if busy else "Sign in")
        self.create_button.setText("Creating account…" if busy else "Create account")

    def _show_error(self, message: str) -> None:
        self.error_label.show_message(message)

    def _clear_error_on_edit(self) -> None:
        """The user is fixing what was wrong, so stop telling them it is wrong."""
        if not self.error_label.isHidden():
            self.viewmodel.clear_error()

    def _remember(self, session: Session) -> None:
        """Save the address and email (never the password) and clear the form."""
        self.settings.server_url = session.client.base_url
        self.settings.last_email = session.user["email"]
        self.server_input.setText(session.client.base_url)
        self.email_input.setText(session.user["email"])
        self._clear_passwords()

    def _clear_passwords(self) -> None:
        for field in (self.password_input, self.register_password_input, self.confirm_input):
            field.clear()
