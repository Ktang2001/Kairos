from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from client.api_client import ApiClient


class NewChatDialog(QDialog):
    """Search the people directory and pick someone to start a 1:1 chat with."""

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Chat")
        self._api_client = api_client

        self.result_user_id: int | None = None
        self.result_user_name: str | None = None

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search by name or email...")
        self.search_input.textChanged.connect(self._on_search_changed)

        self.results_list = QListWidget()
        self.results_list.itemDoubleClicked.connect(lambda _item: self._on_accept())

        self.status_label = QLabel("")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.search_input)
        layout.addWidget(self.results_list)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _on_search_changed(self, text: str) -> None:
        self.results_list.clear()
        text = text.strip()
        if not text:
            return

        try:
            people = self._api_client.search_people(text)
        except Exception as exc:  # noqa: BLE001 - surfaced in the status label, not fatal
            self.status_label.setText(f"Search failed: {exc}")
            return

        self.status_label.setText("" if people else "No matches.")
        for person in people:
            if person["id"] == self._api_client.user_id:
                continue  # can't start a direct chat with yourself
            item = QListWidgetItem(f"{person['name']} <{person['email']}>")
            item.setData(Qt.ItemDataRole.UserRole, person)
            self.results_list.addItem(item)

    def _on_accept(self) -> None:
        item = self.results_list.currentItem()
        if item is None:
            self.status_label.setText("Select someone from the list first.")
            return

        person = item.data(Qt.ItemDataRole.UserRole)
        self.result_user_id = person["id"]
        self.result_user_name = person["name"]
        self.accept()
