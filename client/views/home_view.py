"""The screen shown after signing in.

For now: who is signed in, a sign-out button, and the connectivity-test
message box. Teams, projects and the dashboard will be added here.
"""

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.viewmodels.home_viewmodel import HomeViewModel
from client.views.widgets import ElidedLabel, ErrorLabel
from shared.message_rules import MAX_CONTENT_LENGTH


class HomeView(QWidget):
    def __init__(self, viewmodel: HomeViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.viewmodel = viewmodel

        # Elided, so a long name or address is cut short with "…" (full text
        # on hover) instead of forcing the whole window wider.
        self.signed_in_label = ElidedLabel(f"Signed in as {viewmodel.display_name}")
        self.signed_in_label.setStyleSheet("font-weight: 600;")
        self.server_label = ElidedLabel(f"Server: {viewmodel.server_url}")
        self.sign_out_button = QPushButton("Sign out")

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.addWidget(self.signed_in_label)
        header_text.addWidget(self.server_label)
        header.addLayout(header_text, stretch=1)
        header.addWidget(self.sign_out_button)

        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Send a test message to the host…")
        # Stop at the server's limit rather than letting the user type more
        # and then get a validation error back.
        self.message_input.setMaxLength(MAX_CONTENT_LENGTH)
        self.send_button = QPushButton("Send")
        message_row = QHBoxLayout()
        message_row.addWidget(self.message_input)
        message_row.addWidget(self.send_button)

        self.error_label = ErrorLabel()

        # Plain text only, so message text is shown exactly as typed and can
        # never be rendered as HTML.
        self.log = QPlainTextEdit(readOnly=True)

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addLayout(message_row)
        layout.addWidget(self.error_label)
        layout.addWidget(self.log)

        self.sign_out_button.clicked.connect(self._sign_out)
        self.send_button.clicked.connect(self._send)
        self.message_input.returnPressed.connect(self._send)
        viewmodel.message_sent.connect(self._on_message_sent)
        viewmodel.error_changed.connect(self._show_error)

    def _send(self) -> None:
        self.viewmodel.send_message(self.message_input.text())

    def _on_message_sent(self, content: str) -> None:
        self.log.appendPlainText(f"You: {content}")
        if self.message_input.text().strip() == content:
            self.message_input.clear()

    def _sign_out(self) -> None:
        self.sign_out_button.setEnabled(False)
        self.sign_out_button.setText("Signing out…")
        self.send_button.setEnabled(False)
        self.viewmodel.sign_out()

    def _show_error(self, message: str) -> None:
        self.error_label.show_message(message)
