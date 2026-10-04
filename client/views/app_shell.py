from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.api_client import ApiClient
from client.theme import ThemeManager
from client.views.chat_page import ChatPage
from client.views.dashboard_page import DashboardPage
from client.views.server_settings_page import ServerSettingsPage
from client.views.theme_selector import ThemeSelector

NAV_WIDTH = 140


class AppShell(QMainWindow):
    """The signed-in app: a left-hand nav list (Teams-style) switching between a
    Dashboard tab, a Chat tab, and - only for global admins - a Server Settings tab.
    This is the one place access level actually changes what's on screen: a
    non-admin never sees the nav entry at all, not just a disabled one.
    `on_switch_account` is called if the user wants to disconnect/sign in as
    someone else - the caller (ConnectWindow) decides what that means rather than
    this window owning that navigation.
    """

    def __init__(
        self,
        api_client: ApiClient,
        display_name: str,
        server_label: str,
        on_switch_account,
        is_admin: bool = False,
        theme_manager: ThemeManager | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kairos")
        self.api_client = api_client
        self.theme_manager = theme_manager or ThemeManager()

        nav_items = ["Dashboard", "Chat"]
        if is_admin:
            nav_items.append("Server Settings")

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setFixedWidth(NAV_WIDTH)
        self.nav_list.addItems(nav_items)
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)

        self.dashboard_page = DashboardPage()
        self.chat_page = ChatPage(api_client)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.dashboard_page)
        self.pages.addWidget(self.chat_page)

        self.server_settings_page: ServerSettingsPage | None = None
        if is_admin:
            self.server_settings_page = ServerSettingsPage(api_client)
            self.pages.addWidget(self.server_settings_page)

        self.header_label = QLabel(f"Signed in as {display_name} - {server_label}")
        switch_button = QPushButton("Switch Server / Account")
        switch_button.clicked.connect(on_switch_account)

        header_row = QHBoxLayout()
        header_row.addWidget(self.header_label, stretch=1)
        header_row.addWidget(QLabel("Theme:"))
        header_row.addWidget(ThemeSelector(self.theme_manager))
        header_row.addWidget(switch_button)

        body_row = QHBoxLayout()
        body_row.addWidget(self.nav_list)
        body_row.addWidget(self.pages, stretch=1)

        layout = QVBoxLayout()
        layout.addLayout(header_row)
        layout.addLayout(body_row)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

    def _on_nav_changed(self, index: int) -> None:
        if index >= 0:
            self.pages.setCurrentIndex(index)
