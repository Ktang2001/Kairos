"""The server window: the hosting teammate's on/off switch for the backend.

``python -m server.gui`` opens a small window with a Start/Stop button. Start
runs the API (server/main.py) over HTTPS in a background thread, on the first
free port from 8000, and shows the address teammates connect to plus the
certificate fingerprint. It also announces the server on the local network
(discovery), lets the host rename it and choose the upload folder, and logs
incoming test messages.

MERGE-CRITICAL: keep the plain-text log, the start-up check (``_check_startup``),
the port probe without SO_REUSEADDR, and ``proxy_headers=False``.
Guarded by: tests/server/test_gui.py.
"""

import socket
import sys
import threading
from pathlib import Path

import uvicorn
from PySide6.QtCore import Qt, QTimer
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
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from server.db.session import SessionLocal
from server.discovery_announcer import DiscoveryAnnouncer
from server.main import app
from server.services import message_service, server_settings_service
from server.tls import ensure_server_cert, fingerprint_sha256

#: Listen on every network interface, so teammates' computers can connect.
HOST = "0.0.0.0"
#: The port tried first; if busy, the next free one is used and shown.
PORT = 8000
MAX_PORT_ATTEMPTS = 20
#: How long to wait for uvicorn to report it is listening before giving up.
STARTUP_TIMEOUT_MS = 10_000
STARTUP_POLL_MS = 100
# Shared with the client - see client/main.py - rather than duplicating the asset.
ICON_PATH = Path(__file__).resolve().parent.parent / "client" / "resources" / "kairos.svg"
DESKTOP_FILE_ID = "kairos-server"
TLS_DIR = Path(__file__).resolve().parent / "db" / "tls"
CERT_PATH = TLS_DIR / "cert.pem"
KEY_PATH = TLS_DIR / "key.pem"


def find_free_port(host: str, start_port: int, max_attempts: int = MAX_PORT_ATTEMPTS) -> int:
    """Return the first free port at/after start_port, probed by actually binding it.

    Binding (rather than just checking with a client request) is what catches
    a same-machine occupant regardless of what it does with unauthenticated
    requests - the earlier 8000 collision returned a 401 rather than refusing
    the connection, which a simple "is something answering" check would miss.

    MERGE-CRITICAL: the probe must NOT set SO_REUSEADDR: on Windows that
    option lets a socket bind to a port another program is already listening
    on, so every busy port looked free and the window picked 8000 even while
    it was taken.
    """
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
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
        # Wrap rather than clip: the address clients need is at the end of a
        # long line, and it must be readable (and copyable) in full.
        self.status_label.setWordWrap(True)
        self.status_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.toggle_button = QPushButton("Start Server")
        self.toggle_button.clicked.connect(self._on_toggle_clicked)
        self.fingerprint_label = QLabel("")
        self.fingerprint_label.setWordWrap(True)

        # MERGE-CRITICAL: keep QPlainTextEdit, not QTextEdit. Messages come
        # from the network, and a rich-text box would render HTML in them
        # (fake banners, links, "SYSTEM" senders).
        self.log = QPlainTextEdit(readOnly=True)

        settings_box = self._build_settings_box()

        layout = QVBoxLayout()
        layout.addWidget(self.status_label)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.fingerprint_label)
        layout.addWidget(settings_box)
        layout.addWidget(self.log)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        # While running, check the database for new messages once a second.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(1000)
        self._poll_timer.timeout.connect(self._poll_new_messages)

        # Watches a just-started server until it is really listening (or has
        # died), so "Server running" is only ever shown when it is true.
        self._startup_timer = QTimer(self)
        self._startup_timer.setInterval(STARTUP_POLL_MS)
        self._startup_timer.timeout.connect(self._check_startup)
        self._startup_waited_ms = 0

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
        """Fill the settings box from the database."""
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
        """Let the host pick the upload folder with a folder dialog."""
        chosen = QFileDialog.getExistingDirectory(
            self, "Choose upload folder", self.upload_root_input.text()
        )
        if chosen:
            self.upload_root_input.setText(chosen)

    def _on_save_settings_clicked(self) -> None:
        """Save the display name and upload folder."""
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
        """The one button: starts the server if it is stopped, else stops it."""
        if self._uvicorn_server is None:
            self._start_server()
        else:
            self._stop_server()

    def _start_server(self) -> None:
        """Pick a port, start uvicorn (HTTPS) on a background thread, and begin
        watching it; ``_check_startup`` reports the outcome.
        """
        try:
            port = find_free_port(HOST, PORT)
        except RuntimeError as exc:
            self.status_label.setText(str(exc))
            return

        ensure_server_cert(CERT_PATH, KEY_PATH)

        # MERGE-CRITICAL: proxy_headers=False: there is no proxy in front of
        # Kairos, so an X-Forwarded-For header is always a lie.
        config = uvicorn.Config(
            app,
            host=HOST,
            port=port,
            log_level="info",
            ssl_certfile=str(CERT_PATH),
            ssl_keyfile=str(KEY_PATH),
            proxy_headers=False,
        )
        self._uvicorn_server = uvicorn.Server(config)
        self._server_thread = threading.Thread(target=self._uvicorn_server.run, daemon=True)
        self._server_thread.start()
        self._port = port

        self.status_label.setText(f"Starting server on port {port}…")
        self.toggle_button.setEnabled(False)
        self._startup_waited_ms = 0
        self._startup_timer.start()

    def _check_startup(self) -> None:
        """Report "running" only once uvicorn is listening; report failure if
        its thread died (e.g. the port was taken after all) or it never came up.
        """
        server, thread = self._uvicorn_server, self._server_thread
        if server is None or thread is None:
            self._startup_timer.stop()
            return

        if server.started:
            self._startup_timer.stop()
            port = self._port
            lan_ip = socket.gethostbyname(socket.gethostname())
            note = f" (port {PORT} was taken, picked {port})" if port != PORT else ""
            # The address gets its own line so it never wraps mid-URL. Over a
            # VPN (e.g. Tailscale), clients use this computer's VPN address.
            self.status_label.setText(
                f"Server running{note}.\nGive clients this address:\nhttps://{lan_ip}:{port}"
            )
            self.fingerprint_label.setText(
                "Certificate fingerprint (optional - compare over a trusted channel for "
                f"stronger-than-first-connect assurance): {fingerprint_sha256(CERT_PATH)}"
            )
            self.toggle_button.setText("Stop Server")
            self.toggle_button.setEnabled(True)
            self._poll_timer.start()
            self._announcer = DiscoveryAnnouncer(self._current_display_name, http_port=port)
            self._announcer.start()
            return

        self._startup_waited_ms += STARTUP_POLL_MS
        if not thread.is_alive() or self._startup_waited_ms >= STARTUP_TIMEOUT_MS:
            self._startup_timer.stop()
            port = self._port
            server.should_exit = True
            self._uvicorn_server = None
            self._server_thread = None
            self._port = None
            self.status_label.setText(
                f"Could not start the server on port {port}. Another program may be "
                "using it - close it and try again. (Details are in the terminal.)"
            )
            self.toggle_button.setText("Start Server")
            self.toggle_button.setEnabled(True)

    def _stop_server(self) -> None:
        """Stop announcing, ask uvicorn to finish, wait up to 5 s, reset the window."""
        self._startup_timer.stop()
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
        self.fingerprint_label.setText("")
        self.toggle_button.setText("Start Server")

    def _poll_new_messages(self) -> None:
        """Append messages not shown yet to the log (``_last_seen_id`` tracks
        the newest one shown, so each appears once).
        """
        db = SessionLocal()
        try:
            messages = message_service.list_recent_messages(db, limit=20)
        finally:
            db.close()

        for message in sorted(messages, key=lambda m: m.id):
            if message.id > self._last_seen_id:
                self.log.appendPlainText(
                    f"[{message.created_at}] {message.sender}: {message.content}"
                )
                self._last_seen_id = message.id

    def closeEvent(self, event) -> None:
        # Closing the window must not leave the server running in the background.
        self._stop_server()
        super().closeEvent(event)


def main() -> None:
    """Open the server window (``python -m server.gui``)."""
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
