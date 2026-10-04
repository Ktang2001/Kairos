import httpx
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from client.api_client import ApiClient
from client.net import DiscoveredServer, DiscoveryListener, fetch_server_cert_pem
from client.theme import ThemeManager
from client.viewmodels.identity_viewmodel import IdentityViewModel
from client.viewmodels.server_list_viewmodel import KnownServer, ServerListViewModel
from client.views.add_server_dialog import AddServerDialog
from client.views.app_shell import AppShell
from client.views.auth_dialog import AuthDialog
from client.views.server_tile import ServerTile
from client.views.theme_selector import ThemeSelector

_SECTION_MAX_HEIGHT = 180


def _build_tile_section(title: str) -> tuple[QGroupBox, QVBoxLayout]:
    """A titled, scrollable column of ServerTiles - shared structure for the
    Discovered and Saved sections. The returned layout always keeps one trailing
    stretch item; tiles are inserted before it (see _clear_tiles)."""
    tiles_layout = QVBoxLayout()
    tiles_layout.addStretch()

    tiles_container = QWidget()
    tiles_container.setLayout(tiles_layout)

    scroll_area = QScrollArea()
    scroll_area.setWidgetResizable(True)
    scroll_area.setMaximumHeight(_SECTION_MAX_HEIGHT)
    scroll_area.setWidget(tiles_container)

    box = QGroupBox(title)
    box_layout = QVBoxLayout()
    box_layout.addWidget(scroll_area)
    box.setLayout(box_layout)

    return box, tiles_layout


def _clear_tiles(tiles_layout: QVBoxLayout) -> None:
    """Removes every widget except the trailing stretch item added in
    _build_tile_section."""
    while tiles_layout.count() > 1:
        item = tiles_layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()


def _insert_tile(tiles_layout: QVBoxLayout, tile: QWidget) -> None:
    tiles_layout.insertWidget(tiles_layout.count() - 1, tile)


class ConnectWindow(QMainWindow):
    """Entry screen: pick a server - discovered live on the LAN, or previously
    saved - then sign in or sign up. Once both are done, hands off to AppShell
    (the Teams-style Dashboard/Chat window) and hides itself - "Switch Server /
    Account" in AppShell brings it back.
    """

    def __init__(
        self,
        server_list_vm: ServerListViewModel | None = None,
        identity_vm: IdentityViewModel | None = None,
        theme_manager: ThemeManager | None = None,
        discovery_listener: DiscoveryListener | None = None,
    ) -> None:
        super().__init__()
        self.setWindowTitle("Kairos - Connect")

        self.api_client: ApiClient | None = None
        self.server_list_vm = server_list_vm or ServerListViewModel()
        self.identity_vm = identity_vm or IdentityViewModel()
        self.theme_manager = theme_manager or ThemeManager()
        self.discovery_listener = discovery_listener or DiscoveryListener()
        self._current_server: KnownServer | None = None
        self._app_shell: AppShell | None = None

        discovered_box, self._discovered_tiles_layout = _build_tile_section(
            "Discovered on this network"
        )
        saved_box, self._saved_tiles_layout = _build_tile_section("Saved servers")

        self.add_server_button = QPushButton("Add Server...")
        self.add_server_button.clicked.connect(self._on_add_server_clicked)
        self.status_label = QLabel("Not connected")

        self.identity_label = QLabel("Not signed in")
        self.sign_in_button = QPushButton("Sign In / Sign Up...")
        self.sign_in_button.setEnabled(False)
        self.sign_in_button.clicked.connect(self._on_sign_in_clicked)
        identity_row = QHBoxLayout()
        identity_row.addWidget(self.identity_label)
        identity_row.addWidget(self.sign_in_button)

        theme_row = QHBoxLayout()
        theme_row.addStretch()
        theme_row.addWidget(QLabel("Theme:"))
        theme_row.addWidget(ThemeSelector(self.theme_manager))

        layout = QVBoxLayout()
        layout.addLayout(theme_row)
        layout.addWidget(discovered_box)
        layout.addWidget(saved_box)
        layout.addWidget(self.add_server_button)
        layout.addWidget(self.status_label)
        layout.addLayout(identity_row)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.discovery_listener.server_discovered.connect(self._on_discovery_changed)
        self.discovery_listener.server_lost.connect(self._on_discovery_changed)
        self.discovery_listener.start()

        self._refresh_discovered_tiles()
        self._refresh_saved_tiles()
        self._try_auto_connect_last_used()

    # --- Discovered section ---

    def _on_discovery_changed(self, *_args: object) -> None:
        self._refresh_discovered_tiles()

    def _refresh_discovered_tiles(self) -> None:
        _clear_tiles(self._discovered_tiles_layout)
        servers = self.discovery_listener.known_servers()

        if not servers:
            placeholder = QLabel(
                "No servers found yet - make sure a host nearby has clicked Start Server."
            )
            placeholder.setProperty("muted", True)
            placeholder.setWordWrap(True)
            _insert_tile(self._discovered_tiles_layout, placeholder)
            return

        for server in sorted(servers, key=lambda s: s.name):
            tile = ServerTile(
                name=server.name,
                subtitle=f"{server.host}:{server.port}",
                on_click=lambda s=server: self._on_discovered_tile_clicked(s),
                discovered=True,
            )
            _insert_tile(self._discovered_tiles_layout, tile)

    def _on_discovered_tile_clicked(self, discovered: DiscoveredServer) -> None:
        """Auto-saves a discovered server on first successful click - a separate
        manual "save" step would undercut "zero typing" after the first session."""
        existing = next(
            (
                s
                for s in self.server_list_vm.list_servers()
                if s.host == discovered.host and s.port == discovered.port
            ),
            None,
        )
        server = existing or self.server_list_vm.add_server(
            host=discovered.host, port=discovered.port, display_name_cache=discovered.name
        )
        self._refresh_saved_tiles()
        self._connect_to_server(server)

    # --- Saved section ---

    def _refresh_saved_tiles(self) -> None:
        _clear_tiles(self._saved_tiles_layout)
        servers = self.server_list_vm.list_servers()

        if not servers:
            placeholder = QLabel("No saved servers yet.")
            placeholder.setProperty("muted", True)
            _insert_tile(self._saved_tiles_layout, placeholder)
            return

        for server in servers:
            tile = ServerTile(
                name=server.label,
                subtitle=server.base_url,
                on_click=lambda s=server: self._connect_to_server(s),
                discovered=False,
                on_remove=lambda s=server: self._on_remove_saved_server(s),
            )
            _insert_tile(self._saved_tiles_layout, tile)

    def _on_remove_saved_server(self, server: KnownServer) -> None:
        self.server_list_vm.remove_server(server.id)
        self._refresh_saved_tiles()

    def _try_auto_connect_last_used(self) -> None:
        last_used_id = self.server_list_vm.get_last_used_id()
        if last_used_id is None:
            return
        for server in self.server_list_vm.list_servers():
            if server.id == last_used_id:
                self._connect_to_server(server)
                return

    def _connect_to_server(self, server: KnownServer) -> None:
        """Connecting also refreshes the server's cached display name, in case the
        host renamed it since it was last saved. If we already know who this user
        is on this server, sign-in is silent; otherwise the Sign In dialog opens
        automatically since there's no dashboard to reach without an identity.

        The very first connection to a server pins its TLS certificate
        (trust-on-first-use - see client/net/cert_pinning.py); every later
        connection verifies against exactly that pinned certificate, so a changed
        certificate fails closed here rather than silently succeeding.
        """
        cert_pem = server.cert_pem
        freshly_pinned = cert_pem is None
        if freshly_pinned:
            try:
                cert_pem = fetch_server_cert_pem(server.host, server.port)
            except OSError as exc:
                self.api_client = None
                self._current_server = None
                self.sign_in_button.setEnabled(False)
                self.status_label.setText(f"Connection failed: {exc}")
                return

        client = ApiClient(base_url=server.base_url, cert_pem=cert_pem)
        try:
            client.health()
            info = client.get_server_info()
        except httpx.HTTPError as exc:
            self.api_client = None
            self._current_server = None
            self.sign_in_button.setEnabled(False)
            if not freshly_pinned and "CERTIFICATE_VERIFY_FAILED" in str(exc):
                self.status_label.setText(
                    "This server's identity has changed since you last connected - "
                    "if it wasn't reinstalled/reset, treat this as suspicious."
                )
            else:
                self.status_label.setText(f"Connection failed: {exc}")
            return

        if freshly_pinned:
            self.server_list_vm.update_cert_pem(server.id, cert_pem)

        display_name = info.get("display_name") or server.label
        self.server_list_vm.update_display_name_cache(server.id, display_name)
        self.server_list_vm.mark_connected(server.id)
        self._refresh_saved_tiles()

        self.api_client = client
        self._current_server = server
        self.sign_in_button.setEnabled(True)
        self.status_label.setText(f"Connected to {display_name} ({server.base_url})")

        cached = self.identity_vm.load_cached_identity(server.id)
        if cached is not None:
            user_id, user_name, token = cached
            self.api_client.token = token
            self.api_client.user_id = user_id
            self.identity_label.setText(f"Signed in as {user_name}")
            self._enter_app_shell(user_name, display_name)
        else:
            self.identity_label.setText("Not signed in")
            self._on_sign_in_clicked()

    def _on_add_server_clicked(self) -> None:
        dialog = AddServerDialog(self)
        if dialog.exec() == AddServerDialog.DialogCode.Accepted:
            server = self.server_list_vm.add_server(
                host=dialog.result_host,
                port=dialog.result_port,
                display_name_cache=dialog.result_display_name,
                nickname=dialog.result_nickname,
            )
            self._refresh_saved_tiles()
            self._connect_to_server(server)

    def _on_sign_in_clicked(self) -> None:
        if self.api_client is None or self._current_server is None:
            return

        dialog = AuthDialog(
            self.api_client.base_url, cert_pem=self.api_client.cert_pem, parent=self
        )
        if dialog.exec() != AuthDialog.DialogCode.Accepted:
            return

        self.identity_vm.set_identity(
            self._current_server.id,
            dialog.result_user_id,
            dialog.result_user_name,
            dialog.result_token,
        )
        self.api_client.token = dialog.result_token
        self.api_client.user_id = dialog.result_user_id
        self.identity_label.setText(f"Signed in as {dialog.result_user_name}")

        server_label = self._current_server.label
        self._enter_app_shell(dialog.result_user_name, server_label)

    def _enter_app_shell(self, display_name: str, server_label: str) -> None:
        is_admin = False
        try:
            is_admin = self.api_client.get_my_profile().get("role") == "admin"
        except httpx.HTTPError:
            pass  # default to non-admin rather than fail the whole sign-in

        self._app_shell = AppShell(
            self.api_client,
            display_name=display_name,
            server_label=server_label,
            on_switch_account=self._on_switch_account,
            is_admin=is_admin,
            theme_manager=self.theme_manager,
        )
        self._app_shell.show()
        self.hide()

    def _on_switch_account(self) -> None:
        if self._app_shell is not None:
            self._app_shell.close()
            self._app_shell = None
        if self.api_client is not None:
            try:
                self.api_client.logout()
            except httpx.HTTPError:
                pass  # best-effort - still proceed to sign out locally
        if self._current_server is not None:
            self.identity_vm.clear(self._current_server.id)
        self.identity_label.setText("Not signed in")
        self.show()

    def closeEvent(self, event) -> None:
        self.discovery_listener.stop()
        super().closeEvent(event)
