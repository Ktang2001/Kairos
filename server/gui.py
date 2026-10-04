import socket
import sys
import threading
from pathlib import Path

import uvicorn
from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from server.db.session import SessionLocal
from server.discovery_announcer import DiscoveryAnnouncer
from server.main import app
from server.services import message_service, server_settings_service

HOST = "0.0.0.0"
PORT = 8000
MAX_PORT_ATTEMPTS = 20
# Shared with the client - see client/main.py - rather than duplicating the asset.
ICON_PATH = Path(__file__).resolve().parent.parent / "client" / "resources" / "kairos.svg"
DESKTOP_FILE_ID = "kairos-server"


def find_free_port(host: str, start_port: int, max_attempts: int = MAX_PORT_ATTEMPTS) -> int:
    """Return the first free port at/after start_port, probed by actually binding it.

    Binding (rather than just checking with a client request) is what catches
    a same-machine occupant regardless of what it does with unauthenticated
    requests - the earlier 8000 collision returned a 401 rather than refusing
    the connection, which a simple "is something answering" check would miss.
    """
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise RuntimeError(f"No free port found in range {start_port}-{start_port + max_attempts - 1}")


class ServerWindow(QMainWindow):
    """Lets the hosting teammate start/stop the backend and watch incoming messages."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Kairos Server")

        self._uvicorn_server: uvicorn.Server | None = None
        self._server_thread: threading.Thread | None = None
        self._last_seen_id = 0
        self._port: int | None = None
        self._announcer: DiscoveryAnnouncer | None = None

        self.status_label = QLabel("Server stopped")
        self.toggle_button = QPushButton("Start Server")
        self.toggle_button.clicked.connect(self._on_toggle_clicked)

        self.log = QTextEdit(readOnly=True)

        settings_box = self._build_settings_box()

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.toggle_button)
        layout.addWidget(settings_box)
        layout.addWidget(self.log)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_new_messages)

        self._load_settings()

    def _build_settings_box(self) -> QGroupBox:
        """A user with a global 'admin' role can also change these remotely via
        PUT /server/info (see server/api/server_settings.py) - this panel is just
        the host's own, in-process shortcut to the same server_settings_service.
        """
        box = QGroupBox("Server Settings")

        self.name_input = QLineEdit()
        self.upload_root_input = QLineEdit()
        browse_button = QPushButton("Browse...")
        browse_button.clicked.connect(self._on_browse_upload_root)
        self.save_settings_button = QPushButton("Save Settings")
        self.save_settings_button.clicked.connect(self._on_save_settings_clicked)
        self.settings_status_label = QLabel("")

        upload_root_row = QHBoxLayout()
        upload_root_row.addWidget(self.upload_root_input)
        upload_root_row.addWidget(browse_button)

        form = QFormLayout()
        form.addRow("Display name:", self.name_input)
        form.addRow("Upload folder:", upload_root_row)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.save_settings_button)
        layout.addWidget(self.settings_status_label)
        box.setLayout(layout)
        return box

    def _load_settings(self) -> None:
        db = SessionLocal()
        try:
            settings = server_settings_service.get_settings(db)
            self.name_input.setText(settings.display_name)
            self.upload_root_input.setText(settings.upload_root)
        finally:
            db.close()

    def _current_display_name(self) -> str:
        """Read fresh on every discovery announce (see DiscoveryAnnouncer) so a
        live rename via the Settings box above is picked up by the very next tick."""
        db = SessionLocal()
        try:
            return server_settings_service.get_settings(db).display_name
        finally:
            db.close()

    def _on_browse_upload_root(self) -> None:
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose upload folder", self.upload_root_input.text()
        )
        if chosen:
            self.upload_root_input.setText(chosen)

    def _on_save_settings_clicked(self) -> None:
        db = SessionLocal()
        try:
            server_settings_service.update_settings(
                db,
                display_name=self.name_input.text().strip(),
                upload_root=self.upload_root_input.text().strip(),
            )
        except ValueError as exc:
            self.settings_status_label.setText(f"Could not save: {exc}")
            return
        finally:
            db.close()
        self.settings_status_label.setText("Settings saved.")

    def _on_toggle_clicked(self) -> None:
        if self._uvicorn_server is None:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self) -> None:
        try:
            port = find_free_port(HOST, PORT)
        except RuntimeError as exc:
            self.status_label.setText(str(exc))
            return

        config = uvicorn.Config(app, host=HOST, port=port, log_level="info")
        self._uvicorn_server = uvicorn.Server(config)
        self._server_thread = threading.Thread(target=self._uvicorn_server.run, daemon=True)
        self._server_thread.start()
        self._port = port

        lan_ip = socket.gethostbyname(socket.gethostname())
        note = f" (port {PORT} was taken, picked {port})" if port != PORT else ""
        self.status_label.setText(f"Server running - give clients: http://{lan_ip}:{port}{note}")
        self.toggle_button.setText("Stop Server")
        self._poll_timer.start()

        self._announcer = DiscoveryAnnouncer(self._current_display_name, http_port=port)
        self._announcer.start()

    def _stop_server(self) -> None:
        if self._uvicorn_server is not None:
            self._uvicorn_server.should_exit = True
        if self._server_thread is not None:
            self._server_thread.join(timeout=5)

        if self._announcer is not None:
            self._announcer.stop()
            self._announcer = None

        self._uvicorn_server = None
        self._server_thread = None
        self._port = None
        self._poll_timer.stop()
        self.status_label.setText("Server stopped")
        self.toggle_button.setText("Start Server")

    def _poll_new_messages(self) -> None:
        db = SessionLocal()
        try:
            messages = message_service.list_recent_messages(db, limit=20)
        finally:
            db.close()

        for message in sorted(messages, key=lambda m: m.id):
            if message.id > self._last_seen_id:
                self.log.append(f"[{message.created_at}] {message.sender}: {message.content}")
                self._last_seen_id = message.id

    def closeEvent(self, event) -> None:
        self._stop_server()
        super().closeEvent(event)


def main() -> None:
    app_qt = QApplication(sys.argv)
    app_qt.setWindowIcon(QIcon(str(ICON_PATH)))
    # setWindowIcon() alone only covers the title bar - Wayland taskbars look up
    # the icon via the window's app_id matching an installed .desktop file's
    # Icon= entry instead (see scripts/install_linux_desktop_entries.py).
    app_qt.setDesktopFileName(DESKTOP_FILE_ID)
    window = ServerWindow()
    window.show()
    sys.exit(app_qt.exec())


if __name__ == "__main__":
    main()
