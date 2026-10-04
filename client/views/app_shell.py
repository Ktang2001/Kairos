from PySide6.QtCore import QTimer
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
from client.viewmodels.session import Session
from client.viewmodels.teams_viewmodel import TeamsViewModel
from client.viewmodels.users_viewmodel import UsersViewModel
from client.views.chat_page import ChatPage
from client.views.dashboard_page import DashboardPage
from client.views.server_settings_page import ServerSettingsPage
from client.views.teams_view import TeamsView
from client.views.theme_selector import ThemeSelector
from client.views.users_view import UsersView
from shared.roles import ROLE_ADMIN, ROLE_MEMBER

NAV_WIDTH = 140

#: How often the Teams or Users page, while showing, reloads by itself so other
#: people's changes appear without clicking.
AUTO_REFRESH_MS = 30_000


class AppShell(QMainWindow):
    """The signed-in app: a left-hand nav list switching between Dashboard, Chat,
    Teams and - only for global admins - Users (role changes) and Server Settings.
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
        role: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kairos")
        self.api_client = api_client
        self.theme_manager = theme_manager or ThemeManager()

        nav_items = ["Dashboard", "Chat", "Teams"]
        if is_admin:
            nav_items += ["Users", "Server Settings"]

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setFixedWidth(NAV_WIDTH)
        self.nav_list.addItems(nav_items)
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)

        self.dashboard_page = DashboardPage()
        self.chat_page = ChatPage(api_client)

        # Teams and Users (from the Nick2 branch) share one Session: the
        # connection plus who is signed in. Their view models reload the real
        # role from the server on every load, so this first guess is replaced.
        session = Session(
            client=api_client,
            user={
                "id": api_client.user_id,
                "name": display_name,
                "email": "",
                "role": role or (ROLE_ADMIN if is_admin else ROLE_MEMBER),
            },
        )
        self.teams_viewmodel = TeamsViewModel(session, parent=self)
        self.teams_page = TeamsView(self.teams_viewmodel)

        self.pages = QStackedWidget()
        self.pages.addWidget(self.dashboard_page)
        self.pages.addWidget(self.chat_page)
        self.pages.addWidget(self.teams_page)

        self.users_viewmodel: UsersViewModel | None = None
        self.users_page: UsersView | None = None
        self.server_settings_page: ServerSettingsPage | None = None
        if is_admin:
            self.users_viewmodel = UsersViewModel(session, parent=self)
            self.users_page = UsersView(self.users_viewmodel)
            self.pages.addWidget(self.users_page)
            self.server_settings_page = ServerSettingsPage(api_client)
            self.pages.addWidget(self.server_settings_page)

        # Pages load when first opened (and every AUTO_REFRESH_MS while open),
        # not at sign-in, so the window opens without waiting on the network.
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(AUTO_REFRESH_MS)
        self.refresh_timer.timeout.connect(self.refresh_current_page)
        self.refresh_timer.start()

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
        """Show the chosen page; Teams and Users reload each time they are opened."""
        if index >= 0:
            self.pages.setCurrentIndex(index)
            self.refresh_current_page()

    def refresh_current_page(self) -> None:
        """Reload the Teams or Users page if it is the one showing (queued if a
        load is already running). Other pages manage their own data."""
        current = self.pages.currentWidget()
        if current is self.teams_page:
            self.teams_viewmodel.refresh()
        elif current is not None and current is self.users_page:
            self.users_viewmodel.refresh()
