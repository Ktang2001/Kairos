from collections.abc import Callable

import httpx
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from client.api_client import ApiClient
from client.viewmodels.chat_viewmodel import ChatViewModel
from client.viewmodels.meetings_viewmodel import MeetingsViewModel
from client.views.manage_members_dialog import ManageMembersDialog
from client.views.meeting_card import MeetingCard, meeting_summary
from client.views.meeting_dialog import NewMeetingDialog, edit_meeting
from client.views.teams_view import ask_yes_no

POLL_INTERVAL_MS = 3000


class ChatThreadPanel(QWidget):
    """The right-hand pane of the Chat tab: whichever conversation is currently
    selected on the left, or an empty state if none is yet. Replaces the old
    pop-up ChatWindow - show_conversation() swaps in a fresh ChatViewModel, and
    this panel's one poll QTimer (started once, here) just keeps polling whatever
    conversation is current, rather than one timer per now-defunct popup.

    A message that announces a meeting is shown as that meeting's card. The
    message feed only ever adds messages, so each poll also re-fetches the
    chat's meetings (in the background) to keep the cards' replies and
    cancellations current.
    """

    def __init__(
        self,
        api_client: ApiClient,
        parent: QWidget | None = None,
        meetings: MeetingsViewModel | None = None,
    ) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.view_model: ChatViewModel | None = None
        self.meetings = meetings or MeetingsViewModel(api_client, parent=self)
        #: Asks the user to confirm cancelling a meeting. Replaced in tests.
        self.confirm: Callable[[str, str], bool] = lambda title, question: ask_yes_no(
            self, title, question
        )
        #: The list row of each meeting announced in this chat, by meeting id,
        #: and its card once the meeting's details have arrived.
        self._meeting_rows: dict[int, QListWidgetItem] = {}
        self._meeting_cards: dict[int, MeetingCard] = {}
        self._meetings_loading = False

        self._empty_page = QLabel("Select a conversation to start chatting.")
        self._empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_page.setProperty("muted", True)

        self.title_label = QLabel("")
        self.title_label.setObjectName("chatThreadTitle")
        # Group names are chosen by people: shown as typed, never as HTML.
        self.title_label.setTextFormat(Qt.TextFormat.PlainText)

        self.message_list = QListWidget()
        self.message_list.itemDoubleClicked.connect(self._on_item_double_clicked)

        self.compose_input = QLineEdit()
        self.compose_input.returnPressed.connect(self._on_send)
        self.send_button = QPushButton("Send")
        self.send_button.setProperty("primary", True)
        self.send_button.clicked.connect(self._on_send)
        self.attach_button = QPushButton("Attach File...")
        self.attach_button.clicked.connect(self._on_attach)
        self.meet_button = QPushButton("Meeting...")
        self.meet_button.setToolTip("Start or schedule a Jitsi meeting with everyone in this chat")
        self.meet_button.clicked.connect(self._on_meet)
        self.manage_members_button = QPushButton("Manage Members...")
        self.manage_members_button.clicked.connect(self._on_manage_members)
        # Shown only for group chats, and not for a team's chat: who is in that
        # follows the team, so it is changed from the Teams page instead.
        self.manage_members_button.setVisible(False)

        self.status_label = QLabel("")
        # Error text can quote the server; plain text, never HTML.
        self.status_label.setTextFormat(Qt.TextFormat.PlainText)
        self.status_label.setWordWrap(True)

        compose_row = QHBoxLayout()
        compose_row.addWidget(self.compose_input)
        compose_row.addWidget(self.send_button)
        compose_row.addWidget(self.attach_button)
        compose_row.addWidget(self.meet_button)

        top_row = QHBoxLayout()
        top_row.addWidget(self.title_label, 1)
        top_row.addWidget(self.manage_members_button)

        thread_layout = QVBoxLayout()
        thread_layout.addLayout(top_row)
        thread_layout.addWidget(self.message_list)
        thread_layout.addLayout(compose_row)
        thread_layout.addWidget(self.status_label)
        self._thread_page = QWidget()
        self._thread_page.setLayout(thread_layout)

        self._pages = QStackedWidget()
        self._pages.addWidget(self._empty_page)
        self._pages.addWidget(self._thread_page)

        layout = QVBoxLayout()
        layout.addWidget(self._pages)
        self.setLayout(layout)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._refresh)
        self._poll_timer.start()

        self.meetings.chat_meetings_loaded.connect(self._show_meetings)
        self.meetings.meeting_changed.connect(self._on_meeting_changed)
        self.meetings.busy_changed.connect(self._set_meetings_busy)
        self.meetings.error_changed.connect(self._show_meeting_error)

    def show_conversation(self, conversation_id: int, title: str) -> None:
        self.view_model = ChatViewModel(self.api_client, conversation_id)
        self.title_label.setText(title)
        self.message_list.clear()
        self._meeting_rows = {}
        self._meeting_cards = {}
        self.status_label.setText("")
        self.manage_members_button.setVisible(False)
        self._pages.setCurrentWidget(self._thread_page)

        self._check_if_group(conversation_id)
        self._refresh()

    def _check_if_group(self, conversation_id: int) -> None:
        try:
            conversation = self.api_client.get_conversation(conversation_id)
        except httpx.HTTPError:
            return  # leave the button hidden rather than fail the whole panel
        self.manage_members_button.setVisible(
            conversation["kind"] == "group" and conversation.get("team_id") is None
        )

    def _refresh(self) -> None:
        if self.view_model is None:
            return
        try:
            new_messages = self.view_model.fetch_new_messages()
        except httpx.HTTPError as exc:
            self.status_label.setText(f"Could not refresh: {exc}")
            return

        for message in new_messages:
            self._append_message(message)
        self._load_meetings()

    def _append_message(self, message: dict) -> None:
        sender = self.view_model.sender_label(message["sender_user_id"])
        body = message.get("body") or ""
        attachments = message.get("attachments") or []

        text = f"{sender}: {body}" if body else f"{sender}:"
        if attachments:
            names = ", ".join(a["original_filename"] for a in attachments)
            text = f"{text}  [file: {names}]" if body else f"{sender} sent a file: {names}"

        item = QListWidgetItem(text)
        if attachments:
            item.setData(Qt.ItemDataRole.UserRole, attachments)
        self.message_list.addItem(item)
        # Shown as the announcement's text until the meeting's details arrive
        # (and for good, if they can't be fetched).
        if message.get("meeting_id") is not None:
            self._meeting_rows[message["meeting_id"]] = item

    def _on_send(self) -> None:
        if self.view_model is None:
            return
        body = self.compose_input.text().strip()
        if not body:
            return
        try:
            self.view_model.send_text(body)
        except httpx.HTTPError as exc:
            self.status_label.setText(f"Send failed: {exc}")
            return
        self.compose_input.clear()
        self.status_label.setText("")
        self._refresh()

    def _on_attach(self) -> None:
        if self.view_model is None:
            return
        file_path, _ = QFileDialog.getOpenFileName(self, "Attach File")
        if not file_path:
            return
        try:
            self.view_model.send_attachment(file_path)
        except httpx.HTTPError as exc:
            self.status_label.setText(f"Upload failed: {exc}")
            return
        self.status_label.setText("")
        self._refresh()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        if self.view_model is None:
            return
        attachments = item.data(Qt.ItemDataRole.UserRole)
        if not attachments:
            return
        attachment = attachments[0]
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Save Attachment", attachment["original_filename"]
        )
        if not save_path:
            return
        try:
            self.view_model.download_attachment(attachment["id"], save_path)
        except httpx.HTTPError as exc:
            self.status_label.setText(f"Download failed: {exc}")
            return
        self.status_label.setText(f"Saved to {save_path}")

    def _on_manage_members(self) -> None:
        if self.view_model is None:
            return
        dialog = ManageMembersDialog(
            self.api_client, self.view_model, self.view_model.conversation_id, self
        )
        dialog.exec()

    # ------------------------------------------------------------- meetings

    def _on_meet(self) -> None:
        """Ask for the meeting's details and start or schedule it in this chat."""
        if self.view_model is None:
            return
        dialog = NewMeetingDialog(self)
        if dialog.exec() != NewMeetingDialog.DialogCode.Accepted:
            return
        self.meetings.create_in_chat(
            self.view_model.conversation_id,
            title=dialog.result_title,
            starts_at=dialog.result_starts_at,
            duration_minutes=dialog.result_duration_minutes,
            client_token=dialog.result_client_token,
            reminder_minutes=dialog.result_reminder_minutes,
        )

    def _load_meetings(self) -> None:
        """Re-fetch this chat's meetings for its cards, unless a fetch is running."""
        if self.view_model is None or not self._meeting_rows or self._meetings_loading:
            return
        self._meetings_loading = True
        self.meetings.load_chat_meetings(self.view_model.conversation_id)

    def _show_meetings(self, conversation_id: int, meetings: list[dict]) -> None:
        """Turn announcement rows into cards, and bring existing cards up to date."""
        self._meetings_loading = False
        if self.view_model is None or conversation_id != self.view_model.conversation_id:
            return  # the user has moved on to another chat
        for meeting in meetings:
            self._show_meeting(meeting)

    def _show_meeting(self, meeting: dict) -> None:
        card = self._meeting_cards.get(meeting["id"])
        if card is not None:
            card.show_meeting(meeting)
        else:
            item = self._meeting_rows.get(meeting["id"])
            if item is None:
                return
            card = MeetingCard(meeting)
            card.respond_clicked.connect(self.meetings.respond)
            card.join_clicked.connect(self.meetings.join)
            card.edit_clicked.connect(self._edit_meeting)
            card.cancel_clicked.connect(self._confirm_cancel)
            card.set_busy(self.meetings.busy)
            # The card replaces the row's text (see add_card_item).
            item.setText("")
            self.message_list.setItemWidget(item, card)
            self._meeting_cards[meeting["id"]] = card
        item = self._meeting_rows[meeting["id"]]
        summary = meeting_summary(meeting)
        item.setData(Qt.ItemDataRole.AccessibleTextRole, summary)
        item.setToolTip(summary)
        item.setSizeHint(card.row_size_hint())

    def _on_meeting_changed(self, meeting: dict) -> None:
        """A meeting was made or changed (here or on another page)."""
        if self.view_model is None or meeting["conversation_id"] != self.view_model.conversation_id:
            return
        self._refresh()  # picks up the announcement or "cancelled" message
        self._show_meeting(meeting)

    def _edit_meeting(self, meeting_id: int) -> None:
        """Change a meeting you host: the meeting dialog, filled in."""
        card = self._meeting_cards.get(meeting_id)
        if card is not None:
            edit_meeting(self, self.meetings, card.meeting)

    def _confirm_cancel(self, meeting_id: int) -> None:
        card = self._meeting_cards.get(meeting_id)
        title = card.meeting["title"] if card is not None else "this meeting"
        if self.confirm("Cancel meeting", f'Cancel "{title}" for everyone?'):
            self.meetings.cancel(meeting_id)

    def _set_meetings_busy(self, busy: bool) -> None:
        self.meet_button.setEnabled(not busy)
        for card in self._meeting_cards.values():
            card.set_busy(busy)

    def _show_meeting_error(self, message: str) -> None:
        # A failed fetch must not leave the cards frozen for good.
        self._meetings_loading = False
        # The view model is shared with other pages: only show what happened
        # while this chat is on screen.
        if message and self.isVisible():
            self.status_label.setText(message)
