import httpx
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class AddServerDialog(QDialog):
    """Prompts for a host/port and probes GET /server/info before accepting, so a
    saved server always has a real self-reported display name rather than a guess.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Server")

        self.result_host: str | None = None
        self.result_port: int | None = None
        self.result_display_name: str | None = None
        self.result_nickname: str | None = None

        self.host_input = QLineEdit()
        self.port_input = QSpinBox()
        self.port_input.setRange(1, 65535)
        self.port_input.setValue(8000)
        self.nickname_input = QLineEdit()
        self.status_label = QLabel("")

        form = QFormLayout()
        form.addRow("Host / IP:", self.host_input)
        form.addRow("Port:", self.port_input)
        form.addRow("Nickname (optional):", self.nickname_input)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _on_accept(self) -> None:
        host = self.host_input.text().strip()
        port = self.port_input.value()
        if not host:
            self.status_label.setText("Host is required.")
            return

        # https, and deliberately unverified: this probe runs before the server
        # has ever been pinned (see client/net/cert_pinning.py), so there is no
        # certificate to check against yet. Real trust is established afterward,
        # when connect_window.py fetches and pins the leaf certificate.
        base_url = f"https://{host}:{port}"
        try:
            response = httpx.get(f"{base_url}/server/info", timeout=5, verify=False)
            response.raise_for_status()
            info = response.json()
        except httpx.HTTPError as exc:
            self.status_label.setText(f"Could not reach server: {exc}")
            return

        self.result_host = host
        self.result_port = port
        self.result_display_name = info.get("display_name")
        self.result_nickname = self.nickname_input.text().strip() or None
        self.accept()
