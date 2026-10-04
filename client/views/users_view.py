"""The admin Users screen (context.md goal #2): every account and its role.

Each role is a drop-down. Changing one asks for confirmation, then saves;
cancelling (or the server refusing) puts the drop-down back. Your own row
can't be changed -- the server refuses that too, so the last admin can never
demote themselves.
"""

from collections.abc import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from client.api_client import is_connection_error
from client.viewmodels.users_viewmodel import UsersViewModel
from client.views.teams_view import ask_yes_no
from client.views.widgets import ErrorLabel
from shared.roles import ALL_ROLES, ROLE_DISPLAY_NAMES

NAME_COLUMN, EMAIL_COLUMN, ROLE_COLUMN = 0, 1, 2


class UsersView(QWidget):
    """The admin Users tab: a table of accounts with a role drop-down each. Display only;
    UsersViewModel holds the logic.
    """

    def __init__(self, viewmodel: UsersViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.viewmodel = viewmodel
        #: Asks the user to confirm a role change. Replaced in tests.
        self.confirm: Callable[[str, str], bool] = lambda title, question: ask_yes_no(
            self, title, question
        )

        self.refresh_button = QPushButton("Refresh")
        header = QHBoxLayout()
        header.addWidget(QLabel("Everyone with an account. Change a role with its drop-down."))
        header.addStretch()
        header.addWidget(self.refresh_button)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Name", "Email", "Role"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(
            NAME_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        self.table.horizontalHeader().setSectionResizeMode(
            EMAIL_COLUMN, QHeaderView.ResizeMode.Stretch
        )
        # Wide enough for the longest role ("Project Lead") with its arrow.
        self.table.horizontalHeader().setSectionResizeMode(
            ROLE_COLUMN, QHeaderView.ResizeMode.ResizeToContents
        )

        self.error_label = ErrorLabel()
        self.loading_label = QLabel("Loading users…")

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(self.loading_label)
        layout.addWidget(self.table)
        layout.addWidget(self.error_label)

        self.refresh_button.clicked.connect(viewmodel.refresh)
        viewmodel.users_changed.connect(self._show_users)
        viewmodel.busy_changed.connect(self._set_busy)
        viewmodel.error_changed.connect(self._show_error)

        #: role drop-down for each user id, so tests and code can find them.
        self.role_boxes: dict[int, QComboBox] = {}

    def role_box(self, user_id: int) -> QComboBox:
        """The role drop-down on this user's row."""
        return self.role_boxes[user_id]

    def _show_users(self, users: list[dict]) -> None:
        """Refill the table, one row per user; your own row's drop-down is disabled."""
        self.loading_label.setVisible(not self.viewmodel.loaded)
        self.table.setRowCount(len(users))
        self.role_boxes = {}
        for row, user in enumerate(users):
            # QTableWidgetItem text is always plain text, never rendered as HTML.
            self.table.setItem(row, NAME_COLUMN, QTableWidgetItem(user["name"]))
            self.table.setItem(row, EMAIL_COLUMN, QTableWidgetItem(user["email"]))

            box = QComboBox()
            for role in ALL_ROLES:
                box.addItem(ROLE_DISPLAY_NAMES[role], role)
            box.setCurrentIndex(ALL_ROLES.index(user["role"]))
            if user["id"] == self.viewmodel.my_id:
                box.setEnabled(False)
                box.setToolTip("You can't change your own role - ask another admin.")
            box.activated.connect(lambda _index, uid=user["id"], b=box: self._role_picked(uid, b))
            self.table.setCellWidget(row, ROLE_COLUMN, box)
            self.role_boxes[user["id"]] = box

    def _role_picked(self, user_id: int, box: QComboBox) -> None:
        """A drop-down changed: confirm, then save, or put it back."""
        user = next(u for u in self.viewmodel.users if u["id"] == user_id)
        new_role = box.currentData()
        if new_role == user["role"]:
            return
        question = (
            f"Change {user['name']} from {ROLE_DISPLAY_NAMES[user['role']]} "
            f"to {ROLE_DISPLAY_NAMES[new_role]}?"
        )
        if self.confirm("Change role", question):
            self.viewmodel.set_role(user_id, new_role)
        else:
            box.setCurrentIndex(ALL_ROLES.index(user["role"]))

    def _set_busy(self, busy: bool) -> None:
        """Disable the drop-downs and Refresh while a request is in flight."""
        self.refresh_button.setEnabled(not busy)
        for user_id, box in self.role_boxes.items():
            box.setEnabled(not busy and user_id != self.viewmodel.my_id)

    #: Set by the home screen when its offline banner already reports
    #: "can't reach the server", so this screen doesn't say it a second time.
    connection_errors_shown_elsewhere = False

    def _show_error(self, message: str) -> None:
        """Show an error, unless it is a connection error the offline banner already shows."""
        if self.connection_errors_shown_elsewhere and is_connection_error(message):
            message = ""
        self.error_label.show_message(message)
