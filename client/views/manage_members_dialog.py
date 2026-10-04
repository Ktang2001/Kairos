import httpx
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api_client import ApiClient
from client.viewmodels.chat_viewmodel import ChatViewModel
from client.views.new_chat_dialog import NewChatDialog


def _friendly_error(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        if exc.response.status_code == 409:
            return "Can't do that - a group needs at least one admin."
        if exc.response.status_code == 403:
            return "You need to be an admin of this group to do that."
    return f"Action failed: {exc}"


class ManageMembersDialog(QDialog):
    """A group's member list. Admin-only actions (promote/demote/remove/add) are
    only shown to the signed-in user if they are themselves an admin of this
    conversation - role-based UI, mirroring what the server already enforces.
    """

    def __init__(
        self,
        api_client: ApiClient,
        chat_viewmodel: ChatViewModel,
        conversation_id: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Members")
        self.resize(360, 360)

        self._api_client = api_client
        self._chat_viewmodel = chat_viewmodel  # reused for its sender-name cache
        self._conversation_id = conversation_id
        self._is_admin = False

        self.members_list = QListWidget()
        self.add_member_button = QPushButton("Add Member...")
        self.add_member_button.clicked.connect(self._on_add_member)
        self.status_label = QLabel("")
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)

        layout = QVBoxLayout()
        layout.addWidget(self.members_list)
        layout.addWidget(self.add_member_button)
        layout.addWidget(self.status_label)
        layout.addWidget(close_button)
        self.setLayout(layout)

        self._refresh()

    def _refresh(self) -> None:
        try:
            conversation = self._api_client.get_conversation(self._conversation_id)
        except httpx.HTTPError as exc:
            self.status_label.setText(f"Could not load members: {exc}")
            return

        current_user_id = self._api_client.user_id
        self._is_admin = any(
            p["user_id"] == current_user_id and p["role"] == "admin"
            for p in conversation["participants"]
        )
        self.add_member_button.setEnabled(self._is_admin)

        self.members_list.clear()
        for participant in conversation["participants"]:
            self._add_member_row(participant)

    def _add_member_row(self, participant: dict) -> None:
        name = self._chat_viewmodel.sender_label(participant["user_id"])
        is_self = participant["user_id"] == self._api_client.user_id

        row = QWidget()
        row_layout = QHBoxLayout()
        row_layout.addWidget(QLabel(f"{name} ({participant['role']})"), stretch=1)

        if self._is_admin and not is_self:
            toggle_text = "Demote" if participant["role"] == "admin" else "Promote"
            toggle_button = QPushButton(toggle_text)
            toggle_button.clicked.connect(
                lambda checked=False, uid=participant["user_id"], role=participant[
                    "role"
                ]: self._on_toggle_role(uid, role)
            )
            remove_button = QPushButton("Remove")
            remove_button.clicked.connect(
                lambda checked=False, uid=participant["user_id"]: self._on_remove(uid)
            )
            row_layout.addWidget(toggle_button)
            row_layout.addWidget(remove_button)

        row.setLayout(row_layout)
        item = QListWidgetItem()
        item.setSizeHint(row.sizeHint())
        self.members_list.addItem(item)
        self.members_list.setItemWidget(item, row)

    def _on_toggle_role(self, user_id: int, current_role: str) -> None:
        new_role = "member" if current_role == "admin" else "admin"
        try:
            self._api_client.update_participant_role(self._conversation_id, user_id, new_role)
        except httpx.HTTPError as exc:
            self.status_label.setText(_friendly_error(exc))
            return
        self.status_label.setText("")
        self._refresh()

    def _on_remove(self, user_id: int) -> None:
        try:
            self._api_client.remove_participant(self._conversation_id, user_id)
        except httpx.HTTPError as exc:
            self.status_label.setText(_friendly_error(exc))
            return
        self.status_label.setText("")
        self._refresh()

    def _on_add_member(self) -> None:
        dialog = NewChatDialog(self._api_client, self)
        dialog.setWindowTitle("Add Member")
        if dialog.exec() != NewChatDialog.DialogCode.Accepted:
            return

        try:
            self._api_client.add_participant(self._conversation_id, dialog.result_user_id)
        except httpx.HTTPError as exc:
            self.status_label.setText(_friendly_error(exc))
            return
        self.status_label.setText("")
        self._refresh()
