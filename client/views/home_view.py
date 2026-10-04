"""The screen shown after signing in (context.md goal #3).

A header -- who is signed in, the server, Sign out / Sign out everywhere --
over tabs:

* Teams: create and manage teams (goal #1).
* Messages: the connectivity-test message box.
* Users: change people's roles (goal #2). Admins only; the tab appears or
  disappears if an admin changes your role while you are signed in.

Keeping the data fresh and honest:

* Whichever tab is showing refreshes every ``AUTO_REFRESH_MS`` and whenever
  you switch to it, so other people's changes appear without clicking.
* If the host stops answering, one banner says so (with Retry) instead of
  every tab reporting its own error; it disappears as soon as a request
  gets through again.
"""

from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from client.viewmodels import permissions
from client.viewmodels.attachments import (
    KIND_FILTERS,
    KIND_LABELS,
    AttachmentKind,
    PendingAttachment,
)
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.session_events import SessionEvents
from client.viewmodels.teams_viewmodel import TeamsViewModel
from client.viewmodels.users_viewmodel import UsersViewModel
from client.views.teams_view import TeamsView, ask_yes_no
from client.views.users_view import UsersView
from client.views.widgets import ElidedLabel, ErrorLabel
from shared.message_rules import MAX_CONTENT_LENGTH

#: How often the visible tab reloads by itself.
AUTO_REFRESH_MS = 30_000


class HomeView(QWidget):
    def __init__(
        self,
        viewmodel: HomeViewModel,
        teams_viewmodel: TeamsViewModel | None = None,
        users_viewmodel: UsersViewModel | None = None,
        events: SessionEvents | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.viewmodel = viewmodel
        session = viewmodel.session
        self.teams_viewmodel = teams_viewmodel or TeamsViewModel(session, parent=self)
        self.users_viewmodel = users_viewmodel or UsersViewModel(session, parent=self)
        #: Asks the user to confirm "sign out everywhere". Replaced in tests.
        self.confirm = lambda title, question: ask_yes_no(self, title, question)

        # --------------------------------------------------------- header
        # Elided, so a long name or address is cut short with "…" (full text
        # on hover) instead of forcing the whole window wider.
        self.signed_in_label = ElidedLabel(f"Signed in as {viewmodel.display_name}")
        self.signed_in_label.setStyleSheet("font-weight: 600;")
        self.server_label = ElidedLabel(f"Server: {viewmodel.server_url}")
        self.sign_out_button = QPushButton("Sign out")
        self.sign_out_everywhere_button = QPushButton("Sign out everywhere")
        self.sign_out_everywhere_button.setToolTip(
            "End your session on every computer, e.g. if you think someone else has your password."
        )

        header = QHBoxLayout()
        header_text = QVBoxLayout()
        header_text.addWidget(self.signed_in_label)
        header_text.addWidget(self.server_label)
        header.addLayout(header_text, stretch=1)
        header.addWidget(self.sign_out_everywhere_button)
        header.addWidget(self.sign_out_button)

        # ------------------------------------------------- offline banner
        self.offline_label = QLabel(
            f"Can't reach the server at {viewmodel.server_url}. "
            "Check that it's running - this will clear when it answers."
        )
        self.offline_label.setWordWrap(True)
        self.retry_button = QPushButton("Retry")
        self.offline_banner = QFrame()
        self.offline_banner.setFrameShape(QFrame.Shape.StyledPanel)
        banner_layout = QHBoxLayout(self.offline_banner)
        banner_layout.addWidget(self.offline_label, stretch=1)
        banner_layout.addWidget(self.retry_button)
        self.offline_banner.setVisible(False)

        # --------------------------------------------------- messages tab
        self.message_input = QLineEdit()
        self.message_input.setPlaceholderText("Send a test message to the host…")
        # Stop at the server's limit rather than letting the user type more
        # and then get a validation error back.
        self.message_input.setMaxLength(MAX_CONTENT_LENGTH)
        self.send_button = QPushButton("Send")

        # Attach: one button with a menu for the three kinds. Choosing only
        # *picks* a file; uploading it is TODO(attachments) in HomeViewModel.
        self.attach_button = QToolButton()
        self.attach_button.setText("Attach")
        self.attach_button.setToolTip("Share a file, image or audio clip")
        self.attach_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.attach_menu = QMenu(self.attach_button)
        self.attach_actions = {}
        for kind in AttachmentKind:
            action = self.attach_menu.addAction(KIND_LABELS[kind])
            action.triggered.connect(lambda _checked=False, k=kind: self._choose_attachment(k))
            self.attach_actions[kind] = action
        self.attach_button.setMenu(self.attach_menu)
        #: Asks the user to pick a file of ``kind``; returns a path or "".
        #: Replaced in tests, so no real dialog opens.
        self.pick_file = self._open_file_dialog

        message_row = QHBoxLayout()
        message_row.addWidget(self.attach_button)
        message_row.addWidget(self.message_input)
        message_row.addWidget(self.send_button)

        # The chosen attachment, with a button to remove it. Hidden when empty.
        self.attachment_label = ElidedLabel()
        self.remove_attachment_button = QPushButton("✕")
        self.remove_attachment_button.setToolTip("Remove the attachment")
        self.remove_attachment_button.setFixedWidth(32)
        self.attachment_row = QWidget()
        attachment_layout = QHBoxLayout(self.attachment_row)
        attachment_layout.setContentsMargins(0, 0, 0, 0)
        attachment_layout.addWidget(self.attachment_label, stretch=1)
        attachment_layout.addWidget(self.remove_attachment_button)
        self.attachment_row.setVisible(False)

        self.error_label = ErrorLabel()

        # Plain text only, so message text is shown exactly as typed and can
        # never be rendered as HTML.
        self.log = QPlainTextEdit(readOnly=True)

        self.messages_tab = QWidget()
        messages_layout = QVBoxLayout(self.messages_tab)
        messages_layout.addLayout(message_row)
        messages_layout.addWidget(self.attachment_row)
        messages_layout.addWidget(self.error_label)
        messages_layout.addWidget(self.log)

        # ------------------------------------------------------------ tabs
        self.teams_view = TeamsView(self.teams_viewmodel)
        self.users_view = UsersView(self.users_viewmodel)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.teams_view, "Teams")
        self.tabs.addTab(self.messages_tab, "Messages")

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.offline_banner)
        layout.addWidget(self.tabs)

        # ----------------------------------------------------- refreshing
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(AUTO_REFRESH_MS)
        self.refresh_timer.timeout.connect(self.refresh_current_tab)

        # --------------------------------------------------------- wiring
        self.sign_out_button.clicked.connect(self._sign_out)
        self.sign_out_everywhere_button.clicked.connect(self._sign_out_everywhere)
        self.send_button.clicked.connect(self._send)
        self.message_input.returnPressed.connect(self._send)
        self.remove_attachment_button.clicked.connect(viewmodel.clear_attachment)
        viewmodel.attachment_changed.connect(self._show_attachment)
        self.retry_button.clicked.connect(self.refresh_current_tab)
        self.tabs.currentChanged.connect(lambda _index: self.refresh_current_tab())
        viewmodel.message_sent.connect(self._on_message_sent)
        viewmodel.sending_changed.connect(self._set_sending)
        viewmodel.send_failed.connect(self._give_text_back)
        viewmodel.error_changed.connect(self._show_error)
        self.teams_viewmodel.me_changed.connect(self._on_me_changed)
        if events is not None:
            events.connection_changed.connect(self.set_reachable)
            # The banner is now the one place connection trouble is reported.
            self.teams_view.connection_errors_shown_elsewhere = True
            self.users_view.connection_errors_shown_elsewhere = True
        self._show_users_tab(permissions.can_manage_users(session.user))

    # ------------------------------------------------------------ loading

    def load(self) -> None:
        """Fetch the screen's data and start auto-refreshing. Called once the
        screen is shown.
        """
        self.teams_viewmodel.refresh()
        if permissions.can_manage_users(self.viewmodel.session.user):
            self.users_viewmodel.refresh()
        self.refresh_timer.start()

    def refresh_current_tab(self) -> None:
        """Reload whatever is on screen (queued if it is already loading)."""
        current = self.tabs.currentWidget()
        if current is self.users_view:
            self.users_viewmodel.refresh()
        else:
            # Teams -- or Messages, where nothing needs reloading but a cheap
            # request lets Retry (and the timer) discover the server is back.
            self.teams_viewmodel.refresh()

    @Slot(bool)
    def set_reachable(self, reachable: bool) -> None:
        self.offline_banner.setVisible(not reachable)

    @property
    def offline(self) -> bool:
        return not self.offline_banner.isHidden()

    # -------------------------------------------------------------- role

    def _on_me_changed(self, me: dict) -> None:
        """Your role changed while signed in: update the header and the tabs."""
        self.signed_in_label.set_full_text(f"Signed in as {self.viewmodel.display_name}")
        was_shown = self.tabs.indexOf(self.users_view) != -1
        self._show_users_tab(permissions.can_manage_users(me))
        if permissions.can_manage_users(me) and not was_shown:
            self.users_viewmodel.refresh()

    def _show_users_tab(self, show: bool) -> None:
        index = self.tabs.indexOf(self.users_view)
        if show and index == -1:
            self.tabs.addTab(self.users_view, "Users")
        elif not show and index != -1:
            self.tabs.removeTab(index)

    @property
    def users_tab_visible(self) -> bool:
        return self.tabs.indexOf(self.users_view) != -1

    # ---------------------------------------------------------- messages

    def _send(self) -> None:
        self.viewmodel.send_message(self.message_input.text())

    def _open_file_dialog(self, kind: AttachmentKind) -> str:
        path, _filter = QFileDialog.getOpenFileName(
            self, f"Attach {kind.value}", "", KIND_FILTERS[kind]
        )
        return path

    def _choose_attachment(self, kind: AttachmentKind) -> None:
        path = self.pick_file(kind)
        if path:  # "" means the user cancelled the dialog
            self.viewmodel.attach(path, kind)

    def _show_attachment(self, attachment: PendingAttachment | None) -> None:
        self.attachment_row.setVisible(attachment is not None)
        self.attachment_label.set_full_text(attachment.describe() if attachment else "")

    def _set_sending(self, sending: bool) -> None:
        """Lock the box while a message is on its way, so a second Enter or
        click cannot send it again, and show that something is happening.
        """
        if sending:
            # Cleared at once: the text visibly "leaves", and there is nothing
            # left in the box to send twice. Given back if the send fails.
            self.message_input.clear()
        locked = sending or self.viewmodel.signing_out
        self.message_input.setEnabled(not locked)
        self.send_button.setEnabled(not locked)
        self.attach_button.setEnabled(not locked)
        self.remove_attachment_button.setEnabled(not locked)
        self.send_button.setText("Sending…" if sending else "Send")
        if not locked:
            self.message_input.setFocus()

    def _on_message_sent(self, content: str) -> None:
        self.log.appendPlainText(f"You: {content}")

    def _give_text_back(self, content: str) -> None:
        """A failed send must not lose what the user typed."""
        if not self.message_input.text():
            self.message_input.setText(content)

    def _show_error(self, message: str) -> None:
        self.error_label.show_message(message)

    # ---------------------------------------------------------- sign out

    def _lock_for_sign_out(self, label: str, button: QPushButton) -> None:
        self.refresh_timer.stop()
        for widget in (
            self.sign_out_button,
            self.sign_out_everywhere_button,
            self.send_button,
            self.message_input,
            self.attach_button,
            self.remove_attachment_button,
        ):
            widget.setEnabled(False)
        button.setText(label)

    def _sign_out(self) -> None:
        self._lock_for_sign_out("Signing out…", self.sign_out_button)
        self.viewmodel.sign_out()

    def _sign_out_everywhere(self) -> None:
        if not self.confirm(
            "Sign out everywhere",
            "Sign out on every computer where you're signed in, including this one?",
        ):
            return
        self._lock_for_sign_out("Signing out…", self.sign_out_everywhere_button)
        self.viewmodel.sign_out_everywhere()
