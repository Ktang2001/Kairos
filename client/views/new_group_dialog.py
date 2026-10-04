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


class NewGroupDialog(QDialog):
    """Name a new group and check off members found via search.

    Selections persist across searches (tracked in `_selected`, keyed by user id) -
    otherwise picking a second person after a new search would silently drop the
    first one once their row scrolls out of the results.
    """

    def __init__(self, api_client: ApiClient, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Group Chat")
        self._api_client = api_client
        self._selected: dict[int, str] = {}

        self.result_name: str | None = None
        self.result_member_ids: list[int] = []

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("Group name")

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Search people to add...")
        self.search_input.textChanged.connect(self._on_search_changed)

        self.results_list = QListWidget()
        self.results_list.itemChanged.connect(self._on_item_checked_changed)

        self.selected_label = QLabel("Members: (none yet)")
        self.status_label = QLabel("")

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Name:"))
        layout.addWidget(self.name_input)
        layout.addWidget(self.search_input)
        layout.addWidget(self.results_list)
        layout.addWidget(self.selected_label)
        layout.addWidget(self.status_label)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def _on_search_changed(self, text: str) -> None:
        self.results_list.blockSignals(True)
        self.results_list.clear()
        text = text.strip()
        if text:
            self._populate_results(text)
        self.results_list.blockSignals(False)

    def _populate_results(self, text: str) -> None:
        try:
            people = self._api_client.search_people(text)
        except Exception as exc:  # noqa: BLE001 - surfaced in the status label, not fatal
            self.status_label.setText(f"Search failed: {exc}")
            return

        self.status_label.setText("" if people else "No matches.")
        for person in people:
            if person["id"] == self._api_client.user_id:
                continue  # can't add yourself - you're always the creator/admin
            item = QListWidgetItem(f"{person['name']} <{person['email']}>")
            item.setData(Qt.ItemDataRole.UserRole, person)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            checked = person["id"] in self._selected
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.results_list.addItem(item)

    def _on_item_checked_changed(self, item: QListWidgetItem) -> None:
        person = item.data(Qt.ItemDataRole.UserRole)
        if item.checkState() == Qt.CheckState.Checked:
            self._selected[person["id"]] = person["name"]
        else:
            self._selected.pop(person["id"], None)
        self._update_selected_label()

    def _update_selected_label(self) -> None:
        if not self._selected:
            self.selected_label.setText("Members: (none yet)")
        else:
            self.selected_label.setText("Members: " + ", ".join(self._selected.values()))

    def _on_accept(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            self.status_label.setText("A group name is required.")
            return
        if not self._selected:
            self.status_label.setText("Select at least one other member.")
            return

        self.result_name = name
        self.result_member_ids = list(self._selected.keys())
        self.accept()
