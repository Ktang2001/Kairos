import socket
import sys

import httpx
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from client.api_client import ApiClient
from client.api_client.client import DEFAULT_BASE_URL


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kairos")

        self.api_client: ApiClient | None = None

        self.host_input = QLineEdit(DEFAULT_BASE_URL)
        self.connect_button = QPushButton("Connect")
        self.connect_button.clicked.connect(self._on_connect_clicked)
        self.status_label = QLabel("Not connected")

        self.message_input = QLineEdit()
        self.send_button = QPushButton("Send")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self._on_send_clicked)

        self.log = QTextEdit(readOnly=True)

        host_row = QHBoxLayout()
        host_row.addWidget(self.host_input)
        host_row.addWidget(self.connect_button)

        message_row = QHBoxLayout()
        message_row.addWidget(self.message_input)
        message_row.addWidget(self.send_button)

        layout = QVBoxLayout()
        layout.addLayout(host_row)
        layout.addWidget(self.status_label)
        layout.addLayout(message_row)
        layout.addWidget(self.log)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _on_connect_clicked(self) -> None:
        base_url = self.host_input.text().strip()
        client = ApiClient(base_url=base_url)
        try:
            client.health()
        except httpx.HTTPError as exc:
            self.api_client = None
            self.send_button.setEnabled(False)
            self.status_label.setText(f"Connection failed: {exc}")
            return

        self.api_client = client
        self.send_button.setEnabled(True)
        self.status_label.setText(f"Connected to {base_url}")

    def _on_send_clicked(self) -> None:
        if self.api_client is None:
            return

        content = self.message_input.text().strip()
        if not content:
            return

        try:
            self.api_client.send_message(sender=socket.gethostname(), content=content)
        except httpx.HTTPError as exc:
            self.log.append(f"Send failed: {exc}")
            return

        self.log.append(f"You: {content}")
        self.message_input.clear()


def main() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
