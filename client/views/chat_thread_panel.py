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
from client.views.manage_members_dialog import ManageMembersDialog

POLL_INTERVAL_MS = 3000


class ChatThreadPanel(QWidget):
    """The right-hand pane of the Chat tab: whichever conversation is currently
    selected on the left, or an empty state if none is yet. Replaces the old
    pop-up ChatWindow - show_conversation() swaps in a fresh ChatViewModel, and
    this panel's one poll QTimer (started once, here) just keeps polling whatever
    conversation is current, rather than one timer per now-defunct popup.
    """

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.api_client = api_client
        self.view_model: ChatViewModel | None = None

        self._empty_page = QLabel("Select a conversation to start chatting.")
        self._empty_page.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_page.setProperty("muted", True)

        self.title_label = QLabel("")
        self.title_label.setObjectName("chatThreadTitle")

        self.message_list = QListWidget()
        self.message_list.itemDoubleClicked.connect(self._on_item_double_clicked)

        self.compose_input = QLineEdit()
        self.compose_input.returnPressed.connect(self._on_send)
        self.send_button = QPushButton("Send")
        self.send_button.setProperty("primary", True)
        self.send_button.clicked.connect(self._on_send)
        self.attach_button = QPushButton("Attach File...")
        self.attach_button.clicked.connect(self._on_attach)
        self.manage_members_button = QPushButton("Manage Members...")
        self.manage_members_button.clicked.connect(self._on_manage_members)
        self.manage_members_button.setVisible(False)  # shown only for group chats

        self.status_label = QLabel("")

        compose_row = QHBoxLayout()
        compose_row.addWidget(self.compose_input)
        compose_row.addWidget(self.send_button)
        compose_row.addWidget(self.attach_button)

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

    def show_conversation(self, conversation_id: int, title: str) -> None:
        self.view_model = ChatViewModel(self.api_client, conversation_id)
        self.title_label.setText(title)
        self.message_list.clear()
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
        self.manage_members_button.setVisible(conversation["kind"] == "group")

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
