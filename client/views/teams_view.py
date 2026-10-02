"""The Teams screen (context.md goals #1 and #2).

Left: your teams, and (for admins and project leads) a box to create one.
Right: the selected team -- lead and members -- plus only the actions your
role allows. Actions you can't take are hidden, not just disabled (see
``client.viewmodels.permissions``); the server enforces the rules anyway.

Destructive actions (delete team, remove member, leave) ask first.
"""

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.api_client import is_connection_error
from client.viewmodels import permissions
from client.viewmodels.teams_viewmodel import MAX_TEAM_NAME_LENGTH, TeamsViewModel
from client.views.widgets import ElidedLabel, ErrorLabel
from shared.account_rules import MAX_EMAIL_LENGTH

USER_ID_ROLE = Qt.ItemDataRole.UserRole


def ask_yes_no(parent: QWidget, title: str, question: str) -> bool:
    answer = QMessageBox.question(
        parent,
        title,
        question,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes


class TeamsView(QWidget):
    def __init__(self, viewmodel: TeamsViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.viewmodel = viewmodel
        #: Asks the user to confirm a destructive action. Replaced in tests.
        self.confirm: Callable[[str, str], bool] = lambda title, question: ask_yes_no(
            self, title, question
        )

        # ---------------------------------------------------- left: list
        self.teams_list = QListWidget()
        self.refresh_button = QPushButton("Refresh")
        self.new_team_input = QLineEdit()
        self.new_team_input.setPlaceholderText("New team name")
        self.new_team_input.setMaxLength(MAX_TEAM_NAME_LENGTH)
        self.create_team_button = QPushButton("Create team")
        self.create_row = QWidget()
        create_layout = QHBoxLayout(self.create_row)
        create_layout.setContentsMargins(0, 0, 0, 0)
        create_layout.addWidget(self.new_team_input)
        create_layout.addWidget(self.create_team_button)

        list_header = QHBoxLayout()
        list_header.addWidget(QLabel("Your teams"))
        list_header.addStretch()
        list_header.addWidget(self.refresh_button)

        left = QVBoxLayout()
        left.addLayout(list_header)
        left.addWidget(self.teams_list)
        left.addWidget(self.create_row)

        # ------------------------------------------------- right: detail
        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.team_title = ElidedLabel()
        self.team_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.lead_label = ElidedLabel()
        self.members_list = QListWidget()

        self.rename_input = QLineEdit()
        self.rename_input.setMaxLength(MAX_TEAM_NAME_LENGTH)
        self.rename_button = QPushButton("Rename")
        self.add_member_input = QLineEdit()
        self.add_member_input.setPlaceholderText("teammate@example.com")
        self.add_member_input.setMaxLength(MAX_EMAIL_LENGTH)
        self.add_member_button = QPushButton("Add member")
        self.remove_member_button = QPushButton("Remove selected")
        self.make_lead_button = QPushButton("Make selected the lead")
        self.delete_team_button = QPushButton("Delete team")
        self.leave_team_button = QPushButton("Leave team")

        rename_row = QHBoxLayout()
        rename_row.addWidget(self.rename_input)
        rename_row.addWidget(self.rename_button)
        add_row = QHBoxLayout()
        add_row.addWidget(self.add_member_input)
        add_row.addWidget(self.add_member_button)
        member_actions = QHBoxLayout()
        member_actions.addWidget(self.remove_member_button)
        member_actions.addWidget(self.make_lead_button)

        #: Everything only the team's lead or an admin may do.
        self.manage_panel = QWidget()
        manage_layout = QVBoxLayout(self.manage_panel)
        manage_layout.setContentsMargins(0, 0, 0, 0)
        manage_layout.addLayout(add_row)
        manage_layout.addLayout(member_actions)
        manage_layout.addLayout(rename_row)
        manage_layout.addWidget(self.delete_team_button)

        self.detail_panel = QWidget()
        detail = QVBoxLayout(self.detail_panel)
        detail.setContentsMargins(0, 0, 0, 0)
        detail.addWidget(self.team_title)
        detail.addWidget(self.lead_label)
        detail.addWidget(QLabel("Members"))
        detail.addWidget(self.members_list)
        detail.addWidget(self.manage_panel)
        detail.addWidget(self.leave_team_button)

        right = QVBoxLayout()
        right.addWidget(self.empty_label)
        right.addWidget(self.detail_panel)

        columns = QHBoxLayout()
        columns.addLayout(left, stretch=2)
        columns.addLayout(right, stretch=3)

        self.error_label = ErrorLabel()
        layout = QVBoxLayout(self)
        layout.addLayout(columns)
        layout.addWidget(self.error_label)

        self._buttons = [
            self.refresh_button,
            self.create_team_button,
            self.rename_button,
            self.add_member_button,
            self.remove_member_button,
            self.make_lead_button,
            self.delete_team_button,
            self.leave_team_button,
        ]

        # ------------------------------------------------------- wiring
        self.teams_list.currentItemChanged.connect(self._on_team_clicked)
        self.members_list.currentItemChanged.connect(lambda *_: self._update_member_buttons())
        self.refresh_button.clicked.connect(viewmodel.refresh)
        self.create_team_button.clicked.connect(self._create)
        self.new_team_input.returnPressed.connect(self._create)
        self.rename_button.clicked.connect(self._rename)
        self.rename_input.returnPressed.connect(self._rename)
        self.add_member_button.clicked.connect(self._add_member)
        self.add_member_input.returnPressed.connect(self._add_member)
        self.remove_member_button.clicked.connect(self._remove_member)
        self.make_lead_button.clicked.connect(self._make_lead)
        self.delete_team_button.clicked.connect(self._delete)
        self.leave_team_button.clicked.connect(self._leave)

        viewmodel.teams_changed.connect(self._show_teams)
        viewmodel.team_changed.connect(self._show_team)
        viewmodel.me_changed.connect(lambda _me: self._apply_permissions())
        viewmodel.busy_changed.connect(self._set_busy)
        viewmodel.error_changed.connect(self._show_error)

        self._filling = False
        self._shown_team_id: int | None = None
        self._show_teams(viewmodel.teams)
        self._show_team(viewmodel.team)

    # --------------------------------------------------------------- render

    def _show_teams(self, teams: list[dict]) -> None:
        self._filling = True  # repopulating must not count as the user clicking
        try:
            self.teams_list.clear()
            for team in teams:
                item = QListWidgetItem(f"{team['name']}  ({team['member_count']})")
                item.setData(USER_ID_ROLE, team["id"])
                item.setToolTip(f"Lead: {team['lead']['name']}")
                self.teams_list.addItem(item)
                if team["id"] == self.viewmodel.selected_id:
                    self.teams_list.setCurrentItem(item)
        finally:
            self._filling = False
        self._apply_permissions()

    def _show_team(self, team: dict | None) -> None:
        me = self.viewmodel.me
        self.detail_panel.setVisible(team is not None)
        self.empty_label.setVisible(team is None)
        if team is None:
            self.members_list.clear()
            self._apply_permissions()
            return

        self.team_title.set_full_text(team["name"])
        lead = team["lead"]
        self.lead_label.set_full_text(f"Lead: {lead['name']} ({lead['email']})")
        # Auto-refresh must not wipe out a new name the user is typing: only
        # overwrite the box for a different team, or if it hasn't been edited.
        if team["id"] != self._shown_team_id or not self.rename_input.isModified():
            self.rename_input.setText(team["name"])
        self._shown_team_id = team["id"]

        # Likewise keep the selected member selected across a refresh.
        previously_selected = self._selected_member_id()
        self.members_list.clear()
        for member in team["members"]:
            tags = []
            if member["id"] == lead["id"]:
                tags.append("lead")
            if member["id"] == me.get("id"):
                tags.append("you")
            suffix = f"  [{', '.join(tags)}]" if tags else ""
            item = QListWidgetItem(f"{member['name']} - {member['email']}{suffix}")
            item.setData(USER_ID_ROLE, member["id"])
            self.members_list.addItem(item)
            if member["id"] == previously_selected:
                self.members_list.setCurrentItem(item)
        self._apply_permissions()

    def _apply_permissions(self) -> None:
        """Show only the actions your role allows for what is on screen."""
        me, team = self.viewmodel.me, self.viewmodel.team
        self.create_row.setVisible(permissions.can_create_team(me))

        if not self.viewmodel.loaded:
            self.empty_label.setText("Loading your teams…")
        elif not self.viewmodel.teams:
            self.empty_label.setText(
                "You're not on any teams yet."
                + (
                    " Create one on the left."
                    if permissions.can_create_team(me)
                    else " Ask a team lead to add you."
                )
            )
        else:
            self.empty_label.setText("Select a team to see its members.")

        if team is not None:
            self.manage_panel.setVisible(permissions.can_manage_team(me, team))
            self.leave_team_button.setVisible(permissions.can_leave_team(me, team))
        self._update_member_buttons()

    def _update_member_buttons(self) -> None:
        """Remove / make-lead need a selected member who isn't already the lead."""
        team = self.viewmodel.team
        chosen = self._selected_member_id()
        usable = (
            team is not None
            and chosen is not None
            and chosen != team["lead"]["id"]
            and not self.viewmodel.busy
        )
        self.remove_member_button.setEnabled(usable)
        self.make_lead_button.setEnabled(usable)

    def _set_busy(self, busy: bool) -> None:
        for button in self._buttons:
            button.setEnabled(not busy)
        self.teams_list.setEnabled(not busy)
        self._update_member_buttons()

    # -------------------------------------------------------------- actions

    def _selected_member_id(self) -> int | None:
        item = self.members_list.currentItem()
        return item.data(USER_ID_ROLE) if item else None

    def _selected_member_name(self) -> str:
        item = self.members_list.currentItem()
        return item.text().split(" - ")[0] if item else ""

    def _on_team_clicked(self, current: QListWidgetItem | None, _previous) -> None:
        if self._filling:
            return
        self.viewmodel.select_team(current.data(USER_ID_ROLE) if current else None)

    def _create(self) -> None:
        name = self.new_team_input.text()
        self.viewmodel.create_team(name)
        if self.viewmodel.busy:  # accepted and on its way
            self.new_team_input.clear()

    def _rename(self) -> None:
        self.viewmodel.rename_team(self.rename_input.text())

    def _add_member(self) -> None:
        self.viewmodel.add_member(self.add_member_input.text())
        if self.viewmodel.busy:
            self.add_member_input.clear()

    def _remove_member(self) -> None:
        user_id = self._selected_member_id()
        team = self.viewmodel.team
        if user_id is None or team is None:
            return
        if self.confirm(
            "Remove member", f"Remove {self._selected_member_name()} from {team['name']}?"
        ):
            self.viewmodel.remove_member(user_id)

    def _make_lead(self) -> None:
        user_id = self._selected_member_id()
        team = self.viewmodel.team
        if user_id is None or team is None:
            return
        if self.confirm(
            "Change lead",
            f"Make {self._selected_member_name()} the lead of {team['name']}? "
            "You will no longer be able to manage this team unless you are an admin.",
        ):
            self.viewmodel.make_lead(user_id)

    def _delete(self) -> None:
        team = self.viewmodel.team
        if team and self.confirm("Delete team", f"Delete {team['name']}? This can't be undone."):
            self.viewmodel.delete_team()

    def _leave(self) -> None:
        team = self.viewmodel.team
        if team and self.confirm("Leave team", f"Leave {team['name']}?"):
            self.viewmodel.leave_team()

    #: Set by the home screen when its offline banner already reports
    #: "can't reach the server", so this screen doesn't say it a second time.
    connection_errors_shown_elsewhere = False

    def _show_error(self, message: str) -> None:
        if self.connection_errors_shown_elsewhere and is_connection_error(message):
            message = ""
        self.error_label.show_message(message)
