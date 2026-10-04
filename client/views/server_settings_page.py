import httpx
from PySide6.QtWidgets import QFormLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

from client.api_client import ApiClient


def _friendly_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 403:
            return "You need global admin access to change this."
        if exc.response.status_code == 400:
            try:
                return exc.response.json().get("detail", "Invalid value.")
            except ValueError:
                pass
    return f"Save failed: {exc}"


class ServerSettingsPage(QWidget):
    """Lets a signed-in global admin rename the server or change its config
    remotely (PUT /server/info), without needing physical access to the host's own
    Server GUI. Only ever shown to admins - AppShell decides whether to add this
    page/nav entry at all (see client/views/connect_window.py's role lookup).

    `upload_root` is write-only here: GET /server/info deliberately doesn't expose
    the host's current filesystem path to any client, so the field starts blank and
    is left unchanged unless you type a new value (see server/schemas/server_settings.py).
    """

    def __init__(self, api_client: ApiClient) -> None:
        super().__init__()
        self._api_client = api_client

        self.display_name_input = QLineEdit()
        self.upload_root_input = QLineEdit()
        self.upload_root_input.setPlaceholderText("(leave blank to keep unchanged)")
        self.max_upload_mb_input = QLineEdit()
        self.max_upload_mb_input.setPlaceholderText("(leave blank to keep unchanged)")

        form = QFormLayout()
        form.addRow("Display name:", self.display_name_input)
        form.addRow("Upload folder (host path):", self.upload_root_input)
        form.addRow("Max upload size (MB):", self.max_upload_mb_input)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self._on_save)
        self.status_label = QLabel("")

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.save_button)
        layout.addWidget(self.status_label)
        self.setLayout(layout)

        self._load_current()

    def _load_current(self) -> None:
        try:
            info = self._api_client.get_server_info()
        except httpx.HTTPError as exc:
            self.status_label.setText(f"Could not load server info: {exc}")
            return

        self.display_name_input.setText(info.get("display_name", ""))
        max_bytes = info.get("max_upload_size_bytes")
        if max_bytes:
            self.max_upload_mb_input.setText(str(max_bytes // (1024 * 1024)))

    def _on_save(self) -> None:
        display_name = self.display_name_input.text().strip() or None
        upload_root = self.upload_root_input.text().strip() or None

        max_upload_mb_text = self.max_upload_mb_input.text().strip()
        max_upload_size_bytes = None
        if max_upload_mb_text:
            try:
                max_upload_size_bytes = int(max_upload_mb_text) * 1024 * 1024
            except ValueError:
                self.status_label.setText("Max upload size must be a whole number of MB.")
                return

        try:
            self._api_client.update_server_info(
                display_name=display_name,
                upload_root=upload_root,
                max_upload_size_bytes=max_upload_size_bytes,
            )
        except httpx.HTTPError as exc:
            self.status_label.setText(_friendly_error(exc))
            return

        self.upload_root_input.clear()
        self.status_label.setText("Saved.")
        self._load_current()
