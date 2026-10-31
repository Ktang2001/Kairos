from PySide6.QtCore import QObject, QTimer, Signal, Slot
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
from client.viewmodels.dashboard_viewmodel import DashboardViewModel
from client.viewmodels.meeting_preferences import MeetingPreferences
from client.viewmodels.meeting_reminders import MeetingReminders
from client.viewmodels.meetings_viewmodel import MeetingsViewModel
from client.viewmodels.projects_viewmodel import ProjectsViewModel
from client.viewmodels.session import Session
from client.viewmodels.teams_viewmodel import TeamsViewModel
from client.viewmodels.users_viewmodel import UsersViewModel
from client.views.chat_page import ChatPage
from client.views.dashboard_page import DashboardPage
from client.views.profile_page import ProfilePage
from client.views.projects_view import ProjectsView
from client.views.reminder_popup import ReminderNotifier
from client.views.server_settings_page import ServerSettingsPage
from client.views.teams_view import TeamsView
from client.views.theme_selector import ThemeSelector
from client.views.users_view import UsersView
from shared.roles import ROLE_ADMIN, ROLE_MEMBER

NAV_WIDTH = 140


class _SessionExpiry(QObject):
    """Carries "the server refused our token" from a request's background thread
    to the main thread: a signal emitted on another thread to a main-thread
    object's slot is queued, so the slot runs on the main thread."""

    expired = Signal()


#: How often the Dashboard, Teams, Projects or Users page, while showing,
#: reloads by itself so other people's changes appear without clicking.
AUTO_REFRESH_MS = 30_000


class AppShell(QMainWindow):
    """The signed-in app: a left-hand nav list switching between Dashboard, Chat,
    Teams, Projects (tasks and the Gantt chart), Profile (meeting preferences)
    and - only for global admins - Users (role changes) and Server Settings.
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
        on_session_expired=None,
        meeting_preferences: MeetingPreferences | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Kairos")
        self.api_client = api_client

        # A sign-in that stops being accepted while the app is open (found in
        # use: every page showed "401" instead of asking to sign in again).
        self._on_session_expired = on_session_expired
        self._session_expiry_handled = False
        self._session_expiry = _SessionExpiry(self)
        self._session_expiry.expired.connect(self._handle_session_expired)
        api_client.on_session_expired = self._report_session_expired
        self.theme_manager = theme_manager or ThemeManager()

        nav_items = ["Dashboard", "Chat", "Teams", "Projects", "Profile"]
        if is_admin:
            nav_items += ["Users", "Server Settings"]

        self.nav_list = QListWidget()
        self.nav_list.setObjectName("navList")
        self.nav_list.setFixedWidth(NAV_WIDTH)
        self.nav_list.addItems(nav_items)
        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._on_nav_changed)

        # One set of meeting actions for every page that shows meetings, so a
        # reply made on one page refreshes the others (see MeetingsViewModel).
        self.meeting_preferences = meeting_preferences or MeetingPreferences()
        self.meetings_viewmodel = MeetingsViewModel(
            api_client, self.meeting_preferences, display_name=display_name, parent=self
        )

        # Reminders for your upcoming meetings, while this window is open.
        self.meeting_reminders = MeetingReminders(api_client, self.meeting_preferences, parent=self)
        self.reminder_notifier = ReminderNotifier(self)
        self.meeting_reminders.reminder_due.connect(self.reminder_notifier.notify)
        self.reminder_notifier.join_clicked.connect(self.meetings_viewmodel.join)
        # A meeting made, answered or cancelled here changes who is reminded.
        self.meetings_viewmodel.meeting_changed.connect(
            lambda _meeting: self.meeting_reminders.refresh()
        )

        self.chat_page = ChatPage(api_client, meetings=self.meetings_viewmodel)

        # Dashboard, Teams, Projects and Users share one Session: the
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
        self.dashboard_viewmodel = DashboardViewModel(session, parent=self)
        self.dashboard_page = DashboardPage(self.dashboard_viewmodel, self.meetings_viewmodel)
        self.teams_viewmodel = TeamsViewModel(session, parent=self)
        self.teams_page = TeamsView(self.teams_viewmodel, meetings=self.meetings_viewmodel)
        self.projects_viewmodel = ProjectsViewModel(session, parent=self)
        self.projects_page = ProjectsView(self.projects_viewmodel)
        self.profile_page = ProfilePage(
            self.meeting_preferences, self.meetings_viewmodel, kairos_name=display_name
        )

        self.pages = QStackedWidget()
        self.pages.addWidget(self.dashboard_page)
        self.pages.addWidget(self.chat_page)
        self.pages.addWidget(self.teams_page)
        self.pages.addWidget(self.projects_page)
        self.pages.addWidget(self.profile_page)

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
        # not at sign-in -- except the Dashboard, the first page shown, which
        # starts loading now in the background.
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(AUTO_REFRESH_MS)
        self.refresh_timer.timeout.connect(self.refresh_current_page)
        self.refresh_timer.start()
        self.dashboard_viewmodel.refresh()
        self.meeting_reminders.start()

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

    def _report_session_expired(self) -> None:
        """Called on a request's thread; hands over to the main thread."""
        try:
            self._session_expiry.expired.emit()
        except RuntimeError:  # this window is already gone
            pass

    @Slot()
    def _handle_session_expired(self) -> None:
        """Main thread: stop refreshing and let the caller ask for a sign-in, once
        (several pages' requests can fail with 401 at the same moment)."""
        if self._session_expiry_handled or self._on_session_expired is None:
            return
        self._session_expiry_handled = True
        self.refresh_timer.stop()
        self.meeting_reminders.stop()
        self.reminder_notifier.close_all()
        self._on_session_expired()

    def closeEvent(self, event) -> None:
        """Stop reporting 401s to this window once it's closed."""
        if self.api_client.on_session_expired == self._report_session_expired:
            self.api_client.on_session_expired = None
        self.refresh_timer.stop()
        self.meeting_reminders.stop()
        self.reminder_notifier.close_all()
        super().closeEvent(event)

    def _on_nav_changed(self, index: int) -> None:
        """Show the chosen page; Dashboard, Teams, Projects and Users reload each time they are
        opened."""
        if index >= 0:
            self.pages.setCurrentIndex(index)
            self.refresh_current_page()

    def refresh_current_page(self) -> None:
        """Reload the Dashboard, Teams, Projects or Users page if it is the one
        showing (queued if a load is already running). Other pages manage their
        own data."""
        current = self.pages.currentWidget()
        if current is self.dashboard_page:
            self.dashboard_viewmodel.refresh()
        elif current is self.teams_page:
            self.teams_viewmodel.refresh()
        elif current is self.projects_page:
            self.projects_viewmodel.refresh()
        elif current is not None and current is self.users_page:
            self.users_viewmodel.refresh()
