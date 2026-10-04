import httpx
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from client.api_client import ApiClient
from client.viewmodels.conversation_list_viewmodel import ConversationListViewModel
from client.views.chat_thread_panel import ChatThreadPanel
from client.views.new_chat_dialog import NewChatDialog
from client.views.new_group_dialog import NewGroupDialog


class ChatPage(QWidget):
    """The Chat tab: your conversations (direct + group) on the left, finding
    people to start a new one with, creating group chats, and the selected
    conversation's thread (text + files) inline on the right - single click to
    select, no pop-up windows.
    """

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.api_client = api_client

        self.conversations_list = QListWidget()
        self.conversations_list.currentItemChanged.connect(self._on_selection_changed)

        self.new_chat_button = QPushButton("New Chat...")
        self.new_chat_button.clicked.connect(self._on_new_chat_clicked)
        self.new_group_button = QPushButton("New Group...")
        self.new_group_button.clicked.connect(self._on_new_group_clicked)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.clicked.connect(self.refresh_conversations)

        actions_row = QHBoxLayout()
        actions_row.addWidget(self.new_chat_button)
        actions_row.addWidget(self.new_group_button)
        actions_row.addWidget(self.refresh_button)

        list_layout = QVBoxLayout()
        list_layout.addLayout(actions_row)
        list_layout.addWidget(self.conversations_list)
        list_panel = QWidget()
        list_panel.setLayout(list_layout)

        self.thread_panel = ChatThreadPanel(api_client)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(list_panel)
        splitter.addWidget(self.thread_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout = QVBoxLayout()
        layout.addWidget(splitter)
        self.setLayout(layout)

        self.refresh_conversations()

    def refresh_conversations(self) -> None:
        self.conversations_list.clear()
        conversation_list_vm = ConversationListViewModel(self.api_client)
        try:
            conversations = conversation_list_vm.load_conversations()
        except httpx.HTTPError as exc:
            self.conversations_list.addItem(f"Could not load conversations: {exc}")
            return

        if not conversations:
            self.conversations_list.addItem("No conversations yet - start one above.")
            return

        for conversation in conversations:
            item = QListWidgetItem(conversation["label"])
            item.setData(Qt.ItemDataRole.UserRole, conversation["id"])
            self.conversations_list.addItem(item)

    def _on_selection_changed(self, current: QListWidgetItem, _previous) -> None:
        if current is None:
            return
        conversation_id = current.data(Qt.ItemDataRole.UserRole)
        if conversation_id is None:
            return
        self.thread_panel.show_conversation(conversation_id, title=current.text())

    def _select_conversation(self, conversation_id: int, title: str) -> None:
        """Used after creating a new chat/group - selects it in the list (which
        triggers the thread panel via _on_selection_changed) if it's present,
        otherwise opens it directly."""
        for i in range(self.conversations_list.count()):
            item = self.conversations_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == conversation_id:
                self.conversations_list.setCurrentItem(item)
                return
        self.thread_panel.show_conversation(conversation_id, title=title)

    def _on_new_chat_clicked(self) -> None:
        dialog = NewChatDialog(self.api_client, self)
        if dialog.exec() != NewChatDialog.DialogCode.Accepted:
            return

        try:
            conversation = self.api_client.start_direct_conversation(dialog.result_user_id)
        except httpx.HTTPError as exc:
            self.conversations_list.addItem(f"Could not start chat: {exc}")
            return

        self.refresh_conversations()
        self._select_conversation(conversation["id"], title=f"Chat with {dialog.result_user_name}")

    def _on_new_group_clicked(self) -> None:
        dialog = NewGroupDialog(self.api_client, self)
        if dialog.exec() != NewGroupDialog.DialogCode.Accepted:
            return

        try:
            conversation = self.api_client.create_group_conversation(
                dialog.result_name, dialog.result_member_ids
            )
        except httpx.HTTPError as exc:
            self.conversations_list.addItem(f"Could not create group: {exc}")
            return

        self.refresh_conversations()
        self._select_conversation(conversation["id"], title=dialog.result_name)
