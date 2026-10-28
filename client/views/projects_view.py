"""The Projects screen (context.md goals #4-#6, and the Gantt chart).

Top: which team. Left: the team's projects, and -- for the team's lead or an
admin -- creating, renaming, completing and deleting them. Right, for the
chosen project, two tabs:

* **Tasks**: the task list, and an editor for the chosen (or a new) task:
  title, description, who it's assigned to, start and due dates, status, the
  tasks it waits on, and its subtasks (tick them off as they're done, and
  give each one an assignee and dates).
* **Gantt**: the project's timeline (``client.views.gantt_chart``). Clicking a
  bar opens that task on the Tasks tab.

Actions you can't take are hidden, not just disabled (see
``client.viewmodels.permissions``); the server enforces the rules anyway.
Deleting asks first. The editor is not overwritten by the automatic refresh
while you are typing in it.
"""

from collections.abc import Callable
from datetime import date

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from client.api_client import is_connection_error
from client.viewmodels import permissions
from client.viewmodels.projects_viewmodel import (
    MAX_PROJECT_NAME_LENGTH,
    MAX_TITLE_LENGTH,
    STATUS_LABELS,
    ProjectsViewModel,
)
from client.views.gantt_chart import GanttChart, parse_day
from client.views.teams_view import ask_yes_no
from client.views.widgets import ElidedLabel, ErrorLabel
from shared.date_rules import EARLIEST_TASK_DATE, LATEST_TASK_DATE

ID_ROLE = Qt.ItemDataRole.UserRole
#: A subtask item's bare title (its text also shows the assignee and dates).
TITLE_ROLE = Qt.ItemDataRole.UserRole + 1

#: Task list columns.
TASK_COLUMNS = ("Title", "Assigned to", "Start", "Due", "Status", "Subtasks")

#: The editor holds a brand-new task, not one from the list.
NEW_TASK = "new"


def show_date(value: str | None) -> str:
    """An API date for display ("Nov 02, 2026"), or "" when unset."""
    day = parse_day(value)
    return day.strftime("%b %d, %Y") if day else ""


def is_my_work(task: dict, my_id: int | None) -> bool:
    """True if the task, or any of its subtasks, is assigned to ``my_id``."""
    if my_id is None:
        return False
    if task["assignee"] and task["assignee"]["id"] == my_id:
        return True
    # ``get``: a server from before this field existed sends none.
    return my_id in task.get("subtask_assignee_ids", [])


def subtask_label(subtask: dict) -> str:
    """A subtask's line in the list: its title, then who has it and when, if set."""
    details = []
    if subtask["status"] == "in_progress":
        details.append("in progress")
    if subtask["assignee"]:
        details.append(subtask["assignee"]["name"])
    start, due = parse_day(subtask["start_date"]), parse_day(subtask["due_date"])
    if start and due:
        details.append(f"{start:%b %d} - {due:%b %d}")
    elif due:
        details.append(f"due {due:%b %d}")
    elif start:
        details.append(f"from {start:%b %d}")
    return subtask["title"] + (f"  ({', '.join(details)})" if details else "")


def _qdate(value: date) -> QDate:
    """A ``date`` as a ``QDate``."""
    return QDate(value.year, value.month, value.day)


class OptionalDateEdit(QWidget):
    """A date that may be left unset: a checkbox, then a date picker it enables."""

    def __init__(self, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.check = QCheckBox(label)
        self.edit = QDateEdit()
        self.edit.setCalendarPopup(True)
        self.edit.setDisplayFormat("MMM d, yyyy")
        # The same range the server accepts, so no stored date is ever clamped.
        self.edit.setDateRange(_qdate(EARLIEST_TASK_DATE), _qdate(LATEST_TASK_DATE))
        self.edit.setDate(QDate.currentDate())
        self.edit.setEnabled(False)
        self.check.toggled.connect(self.edit.setEnabled)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.check)
        layout.addWidget(self.edit, stretch=1)

    def value(self) -> date | None:
        """The chosen date, or None when the box is unticked."""
        if not self.check.isChecked():
            return None
        return self.edit.date().toPython()

    def set_value(self, value: date | None) -> None:
        """Show ``value``, or untick the box for None (keeping today in the picker)."""
        self.check.setChecked(value is not None)
        self.edit.setDate(_qdate(value) if value else QDate.currentDate())


class ProjectsView(QWidget):
    """The Projects tab. Display only; ProjectsViewModel holds the logic."""

    def __init__(self, viewmodel: ProjectsViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.viewmodel = viewmodel
        #: Asks the user to confirm a destructive action. Replaced in tests.
        self.confirm: Callable[[str, str], bool] = lambda title, question: ask_yes_no(
            self, title, question
        )
        self._filling = False
        #: Which task the editor holds: a task id, NEW_TASK, or None (nothing yet).
        self._form_task: int | str | None = None
        #: The user has changed the editor since it was last filled.
        self._form_dirty = False
        #: The assignee of the task last loaded into the editor.
        self._pending_assignee: int | None = None
        #: The project whose name is in the rename box.
        self._shown_project_id: int | None = None

        # ------------------------------------------------------- top: team
        self.team_combo = QComboBox()
        self.team_combo.setMinimumWidth(200)
        self.refresh_button = QPushButton("Refresh")
        top = QHBoxLayout()
        top.addWidget(QLabel("Team:"))
        top.addWidget(self.team_combo)
        top.addStretch()
        top.addWidget(self.refresh_button)

        # ------------------------------------------------- left: projects
        self.projects_list = QListWidget()
        self.new_project_input = QLineEdit()
        self.new_project_input.setPlaceholderText("New project name")
        self.new_project_input.setMaxLength(MAX_PROJECT_NAME_LENGTH)
        self.create_project_button = QPushButton("Create")
        self.rename_project_input = QLineEdit()
        self.rename_project_input.setMaxLength(MAX_PROJECT_NAME_LENGTH)
        self.rename_project_button = QPushButton("Rename")
        self.complete_project_button = QPushButton("Mark completed")
        self.delete_project_button = QPushButton("Delete project")

        create_row = QHBoxLayout()
        create_row.addWidget(self.new_project_input)
        create_row.addWidget(self.create_project_button)
        rename_row = QHBoxLayout()
        rename_row.addWidget(self.rename_project_input)
        rename_row.addWidget(self.rename_project_button)

        #: Only the team's lead or an admin sees these.
        self.project_manage_panel = QWidget()
        manage = QVBoxLayout(self.project_manage_panel)
        manage.setContentsMargins(0, 0, 0, 0)
        manage.addLayout(create_row)
        manage.addLayout(rename_row)
        manage.addWidget(self.complete_project_button)
        manage.addWidget(self.delete_project_button)

        left_panel = QWidget()
        left = QVBoxLayout(left_panel)
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(QLabel("Projects"))
        left.addWidget(self.projects_list)
        left.addWidget(self.project_manage_panel)

        # ------------------------------------------------ right: project
        self.empty_label = QLabel()
        self.empty_label.setWordWrap(True)
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.project_title = ElidedLabel()
        self.project_title.setStyleSheet("font-size: 16px; font-weight: 600;")
        self.project_summary = QLabel()
        #: Shown for a completed project, whose work is read-only.
        self.read_only_label = QLabel()
        self.read_only_label.setWordWrap(True)
        self.read_only_label.setStyleSheet("font-weight: 600;")

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_tasks_tab(), "Tasks")
        self.tabs.addTab(self._build_gantt_tab(), "Gantt")

        self.project_panel = QWidget()
        project_layout = QVBoxLayout(self.project_panel)
        project_layout.setContentsMargins(0, 0, 0, 0)
        project_layout.addWidget(self.project_title)
        project_layout.addWidget(self.project_summary)
        project_layout.addWidget(self.read_only_label)
        project_layout.addWidget(self.tabs, stretch=1)

        right_panel = QWidget()
        right = QVBoxLayout(right_panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.addWidget(self.empty_label)
        right.addWidget(self.project_panel, stretch=1)

        splitter = QSplitter()
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setSizes([240, 960])

        self.error_label = ErrorLabel()
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(splitter, stretch=1)
        layout.addWidget(self.error_label)

        self._buttons = [
            self.refresh_button,
            self.create_project_button,
            self.rename_project_button,
            self.complete_project_button,
            self.delete_project_button,
            self.new_task_button,
            self.save_task_button,
            self.delete_task_button,
            self.add_dependency_button,
            self.remove_dependency_button,
            self.add_subtask_button,
            self.delete_subtask_button,
            self.save_subtask_button,
        ]

        # ------------------------------------------------------- wiring
        self.team_combo.currentIndexChanged.connect(self._on_team_chosen)
        self.refresh_button.clicked.connect(viewmodel.refresh)
        self.projects_list.currentItemChanged.connect(self._on_project_clicked)
        self.create_project_button.clicked.connect(self._create_project)
        self.new_project_input.returnPressed.connect(self._create_project)
        self.rename_project_button.clicked.connect(self._rename_project)
        self.rename_project_input.returnPressed.connect(self._rename_project)
        self.complete_project_button.clicked.connect(self._toggle_project_completed)
        self.delete_project_button.clicked.connect(self._delete_project)

        self.tasks_table.itemSelectionChanged.connect(self._on_task_clicked)
        self.new_task_button.clicked.connect(self._start_new_task)
        self.only_mine_check.toggled.connect(self._on_only_mine_toggled)
        self.save_task_button.clicked.connect(self._save_task)
        self.delete_task_button.clicked.connect(self._delete_task)
        self.add_dependency_button.clicked.connect(self._add_dependency)
        self.remove_dependency_button.clicked.connect(self._remove_dependency)
        self.add_subtask_button.clicked.connect(self._add_subtask)
        self.subtask_input.returnPressed.connect(self._add_subtask)
        self.delete_subtask_button.clicked.connect(self._delete_subtask)
        self.subtasks_list.itemChanged.connect(self._on_subtask_ticked)
        self.subtasks_list.currentItemChanged.connect(self._on_subtask_selected)
        self.save_subtask_button.clicked.connect(self._save_subtask)
        for signal in (
            self.subtask_title_input.textEdited,
            self.subtask_status_combo.currentIndexChanged,
            self.subtask_assignee_combo.currentIndexChanged,
            self.subtask_start_input.check.toggled,
            self.subtask_start_input.edit.dateChanged,
            self.subtask_due_input.check.toggled,
            self.subtask_due_input.edit.dateChanged,
        ):
            signal.connect(self._mark_subtask_dirty)
        for signal in (
            self.title_input.textEdited,
            self.description_input.textChanged,
            self.assignee_combo.currentIndexChanged,
            self.status_combo.currentIndexChanged,
            self.start_input.check.toggled,
            self.start_input.edit.dateChanged,
            self.due_input.check.toggled,
            self.due_input.edit.dateChanged,
        ):
            signal.connect(self._mark_dirty)

        self.zoom_in_button.clicked.connect(lambda: self.gantt_chart.zoom(1))
        self.zoom_out_button.clicked.connect(lambda: self.gantt_chart.zoom(-1))
        self.gantt_chart.task_clicked.connect(self._open_task_from_chart)

        viewmodel.save_conflicted.connect(self._keep_unsaved_edits)
        viewmodel.changed.connect(self._render)
        viewmodel.me_changed.connect(lambda _me: self._apply_permissions())
        viewmodel.busy_changed.connect(self._set_busy)
        viewmodel.error_changed.connect(self._show_error)

        self._render()

    # ------------------------------------------------------- tab builders

    def _build_tasks_tab(self) -> QWidget:
        """The task list beside the editor for one task."""
        self.tasks_table = QTableWidget(0, len(TASK_COLUMNS))
        self.tasks_table.setHorizontalHeaderLabels(TASK_COLUMNS)
        self.tasks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tasks_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tasks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tasks_table.verticalHeader().setVisible(False)
        header = self.tasks_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, len(TASK_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.new_task_button = QPushButton("New task")
        #: Show only tasks assigned to you, or with subtasks assigned to you.
        self.only_mine_check = QCheckBox("Only my work")
        list_buttons = QHBoxLayout()
        list_buttons.addWidget(self.new_task_button)
        list_buttons.addStretch()
        list_buttons.addWidget(self.only_mine_check)

        list_panel = QWidget()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.addWidget(self.tasks_table)
        list_layout.addLayout(list_buttons)

        # The editor.
        self.editor_box = QGroupBox("New task")
        self.title_input = QLineEdit()
        self.title_input.setMaxLength(MAX_TITLE_LENGTH)
        self.description_input = QPlainTextEdit()
        self.description_input.setFixedHeight(64)
        self.assignee_combo = QComboBox()
        self.start_input = OptionalDateEdit("Start")
        self.due_input = OptionalDateEdit("Due")
        self.status_combo = QComboBox()
        for value, label in STATUS_LABELS.items():
            self.status_combo.addItem(label, value)
        self.save_task_button = QPushButton("Create task")
        self.delete_task_button = QPushButton("Delete task")

        form = QFormLayout()
        form.addRow("Title", self.title_input)
        form.addRow("Description", self.description_input)
        form.addRow("Assigned to", self.assignee_combo)
        form.addRow("Dates", self.start_input)
        form.addRow("", self.due_input)
        form.addRow("Status", self.status_combo)
        task_buttons = QHBoxLayout()
        task_buttons.addWidget(self.save_task_button)
        task_buttons.addStretch()
        task_buttons.addWidget(self.delete_task_button)

        # Waits on (dependencies).
        self.dependencies_list = QListWidget()
        self.dependencies_list.setMaximumHeight(80)
        self.dependency_combo = QComboBox()
        self.add_dependency_button = QPushButton("Add")
        self.remove_dependency_button = QPushButton("Remove selected")
        dependency_row = QHBoxLayout()
        dependency_row.addWidget(self.dependency_combo, stretch=1)
        dependency_row.addWidget(self.add_dependency_button)

        # Subtasks.
        self.subtasks_list = QListWidget()
        self.subtasks_list.setMaximumHeight(110)
        self.subtask_input = QLineEdit()
        self.subtask_input.setPlaceholderText("New subtask")
        self.subtask_input.setMaxLength(MAX_TITLE_LENGTH)
        self.add_subtask_button = QPushButton("Add")
        self.delete_subtask_button = QPushButton("Delete selected")
        subtask_row = QHBoxLayout()
        subtask_row.addWidget(self.subtask_input, stretch=1)
        subtask_row.addWidget(self.add_subtask_button)

        # The selected subtask's title, status, assignee and dates (goals 4-6).
        self.subtask_title_input = QLineEdit()
        self.subtask_title_input.setMaxLength(MAX_TITLE_LENGTH)
        self.subtask_status_combo = QComboBox()
        for value, label in STATUS_LABELS.items():
            self.subtask_status_combo.addItem(label, value)
        self.subtask_assignee_combo = QComboBox()
        self.subtask_start_input = OptionalDateEdit("Start")
        self.subtask_due_input = OptionalDateEdit("Due")
        self.save_subtask_button = QPushButton("Save subtask")
        self.subtask_editor = QGroupBox("Selected subtask")
        subtask_form = QFormLayout(self.subtask_editor)
        subtask_form.addRow("Title", self.subtask_title_input)
        subtask_form.addRow("Status", self.subtask_status_combo)
        subtask_form.addRow("Assigned to", self.subtask_assignee_combo)
        subtask_form.addRow("Dates", self.subtask_start_input)
        subtask_form.addRow("", self.subtask_due_input)
        subtask_form.addRow("", self.save_subtask_button)
        #: Which subtask the small editor holds, and whether the user has changed it.
        self._subtask_form_id: int | None = None
        self._subtask_dirty = False

        #: Dependencies and subtasks need a saved task.
        self.saved_task_panel = QWidget()
        saved = QVBoxLayout(self.saved_task_panel)
        saved.setContentsMargins(0, 0, 0, 0)
        waits_label = QLabel("Waits on (can't start until these are done)")
        waits_label.setWordWrap(True)
        saved.addWidget(waits_label)
        saved.addWidget(self.dependencies_list)
        saved.addLayout(dependency_row)
        saved.addWidget(self.remove_dependency_button, alignment=Qt.AlignmentFlag.AlignLeft)
        saved.addWidget(QLabel("Subtasks (tick when done)"))
        saved.addWidget(self.subtasks_list)
        saved.addLayout(subtask_row)
        saved.addWidget(self.delete_subtask_button, alignment=Qt.AlignmentFlag.AlignLeft)
        saved.addWidget(self.subtask_editor)

        editor = QVBoxLayout(self.editor_box)
        editor.addLayout(form)
        editor.addLayout(task_buttons)
        editor.addWidget(self.saved_task_panel)
        editor.addStretch()

        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        editor_scroll.setMinimumWidth(360)
        editor_scroll.setWidget(self.editor_box)

        splitter = QSplitter()
        splitter.addWidget(list_panel)
        splitter.addWidget(editor_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([560, 400])
        return splitter

    def _build_gantt_tab(self) -> QWidget:
        """The chart in a scroll area, with zoom buttons, a legend and the unscheduled list."""
        self.gantt_chart = GanttChart()
        self.zoom_in_button = QPushButton("Zoom in")
        self.zoom_out_button = QPushButton("Zoom out")
        legend = QLabel(
            "Grey: to do   Blue: in progress   Green: done   "
            "Red outline: overdue   Dashed: only one date set   "
            "Red arrow: starts before what it waits on ends"
        )
        legend.setWordWrap(True)
        legend.setProperty("muted", True)
        controls = QHBoxLayout()
        controls.addWidget(self.zoom_out_button)
        controls.addWidget(self.zoom_in_button)
        controls.addWidget(legend, stretch=1)

        scroll = QScrollArea()
        scroll.setWidget(self.gantt_chart)
        scroll.setWidgetResizable(False)

        self.unscheduled_label = QLabel()
        self.unscheduled_label.setWordWrap(True)
        self.unscheduled_label.setTextFormat(Qt.TextFormat.PlainText)

        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.addLayout(controls)
        layout.addWidget(scroll, stretch=1)
        layout.addWidget(self.unscheduled_label)
        return panel

    # ------------------------------------------------------------- render

    def _render(self) -> None:
        """Show everything the view model holds."""
        vm = self.viewmodel
        self._filling = True  # refilling widgets must not count as the user acting
        try:
            self._fill_teams()
            self._fill_projects()
            self._fill_project()
            self._fill_tasks()
            self._fill_editor()
            self.gantt_chart.set_chart(vm.gantt)
            self.gantt_chart.adjustSize()
            self._fill_unscheduled()
        finally:
            self._filling = False
        self._apply_permissions()

    def _fill_teams(self) -> None:
        """The team picker, with the chosen team selected."""
        vm = self.viewmodel
        self.team_combo.clear()
        for team in vm.teams:
            self.team_combo.addItem(team["name"], team["id"])
            if team["id"] == vm.team_id:
                self.team_combo.setCurrentIndex(self.team_combo.count() - 1)

    def _fill_projects(self) -> None:
        """The project list: name, how many tasks are done, and completed ones marked."""
        vm = self.viewmodel
        self.projects_list.clear()
        for project in vm.projects:
            counts = project["tasks"]
            text = f"{project['name']}  ({counts['done']}/{counts['total']} done)"
            if project["status"] == "completed":
                text += "  [completed]"
            item = QListWidgetItem(text)
            item.setData(ID_ROLE, project["id"])
            self.projects_list.addItem(item)
            if project["id"] == vm.project_id:
                self.projects_list.setCurrentItem(item)

    def _fill_project(self) -> None:
        """The chosen project's heading, or the empty message."""
        vm = self.viewmodel
        project = vm.project
        self.project_panel.setVisible(project is not None)
        self.empty_label.setVisible(project is None)
        if not vm.loaded:
            self.empty_label.setText("Loading your projects…")
        elif not vm.teams:
            self.empty_label.setText("You're not on any teams yet. Join a team on the Teams tab.")
        elif project is None:
            can_create = vm.team is not None and permissions.can_manage_projects(vm.me, vm.team)
            self.empty_label.setText(
                "This team has no projects yet."
                + (
                    " Create one on the left."
                    if can_create
                    else " Ask the team lead to create one."
                )
            )
        if project is None:
            return
        self.project_title.set_full_text(project["name"])
        counts = project["tasks"]
        overdue = sum(1 for row in (vm.gantt or {}).get("rows", []) if row["overdue"])
        summary = (
            f"{counts['total']} tasks: {counts['todo']} to do, "
            f"{counts['in_progress']} in progress, {counts['done']} done"
        )
        if overdue:
            summary += f"  -  {overdue} overdue"
        if project["status"] == "completed":
            summary += "  -  project completed"
        self.project_summary.setText(summary)
        # Auto-refresh must not wipe out a new name the user is typing.
        if project["id"] != self._shown_project_id or not self.rename_project_input.isModified():
            self.rename_project_input.setText(project["name"])
        self._shown_project_id = project["id"]
        self.complete_project_button.setText(
            "Reopen project" if project["status"] == "completed" else "Mark completed"
        )

    def _fill_tasks(self) -> None:
        """The task table, with the open task selected.

        The fit-to-contents columns are switched off while the cells go in and
        fitted once at the end. Left on, Qt re-measures every row after each
        cell, which made the redraw grow with the square of the task count
        (found by stress testing: 400 tasks froze the window for 12 s on every
        automatic refresh).
        """
        vm = self.viewmodel
        tasks = self.shown_tasks()
        table = self.tasks_table
        header = table.horizontalHeader()
        table.setUpdatesEnabled(False)
        for column in range(1, len(TASK_COLUMNS)):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.Interactive)
        try:
            self._fill_task_rows(tasks)
        finally:
            for column in range(1, len(TASK_COLUMNS)):
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
            table.setUpdatesEnabled(True)
        table.clearSelection()
        if vm.task_id is not None:
            for row, task in enumerate(tasks):
                if task["id"] == vm.task_id:
                    table.selectRow(row)

    def shown_tasks(self) -> list[dict]:
        """The tasks the table shows: all of them, or only your work when ticked."""
        tasks = self.viewmodel.tasks
        if not self.only_mine_check.isChecked():
            return tasks
        my_id = self.viewmodel.me.get("id")
        return [task for task in tasks if is_my_work(task, my_id)]

    def _fill_task_rows(self, tasks: list[dict]) -> None:
        """Put one row per task into the table."""
        self.tasks_table.setRowCount(len(tasks))
        my_id = self.viewmodel.me.get("id")
        for row, task in enumerate(tasks):
            assignee = task["assignee"]["name"] if task["assignee"] else "—"
            task_is_mine = task["assignee"] is not None and task["assignee"]["id"] == my_id
            if not task_is_mine and is_my_work(task, my_id):
                assignee += " (your subtasks)"
            subtasks = (
                f"{task['subtasks_done']}/{task['subtasks_total']}"
                if task["subtasks_total"]
                else ""
            )
            cells = (
                task["title"],
                assignee,
                show_date(task["start_date"]),
                show_date(task["due_date"]),
                STATUS_LABELS.get(task["status"], task["status"]),
                subtasks,
            )
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setData(ID_ROLE, task["id"])
                self.tasks_table.setItem(row, column, item)

    def _fill_editor(self) -> None:
        """Load the open task into the editor -- unless the user is editing that same task."""
        vm = self.viewmodel
        target: int | str | None = vm.task_id if vm.task is not None else NEW_TASK
        same = target == self._form_task
        if not (same and self._form_dirty):
            self._load_form(vm.task)
            self._form_task = target
            self._form_dirty = False
        self._fill_assignees(keep_choice=same and self._form_dirty)
        self._fill_dependencies()
        self._fill_subtasks()

    def _load_form(self, task: dict | None) -> None:
        """Put ``task`` (or a blank new task) into the editor fields."""
        self.editor_box.setTitle(f"Task: {task['title']}" if task else "New task")
        self.save_task_button.setText("Save changes" if task else "Create task")
        self.title_input.setText(task["title"] if task else "")
        self.description_input.setPlainText((task or {}).get("description") or "")
        self.start_input.set_value(parse_day(task["start_date"]) if task else None)
        self.due_input.set_value(parse_day(task["due_date"]) if task else None)
        status = task["status"] if task else "todo"
        self.status_combo.setCurrentIndex(max(0, self.status_combo.findData(status)))
        self._pending_assignee = task["assignee"]["id"] if task and task["assignee"] else None

    def _fill_assignees(self, keep_choice: bool) -> None:
        """The assignee picker: "Unassigned" and the team's members."""
        current = self.assignee_combo.currentData() if keep_choice else self._pending_assignee
        self.assignee_combo.clear()
        self.assignee_combo.addItem("Unassigned", None)
        team = self.viewmodel.team
        for member in team["members"] if team else []:
            self.assignee_combo.addItem(member["name"], member["id"])
        self.assignee_combo.setCurrentIndex(max(0, self.assignee_combo.findData(current)))

    def _fill_dependencies(self) -> None:
        """What the open task waits on, and the other tasks it could wait on."""
        vm = self.viewmodel
        titles = {t["id"]: t["title"] for t in vm.tasks}
        waits_on = vm.task["depends_on"] if vm.task else []
        self.dependencies_list.clear()
        for other in waits_on:
            item = QListWidgetItem(titles.get(other, f"Task {other}"))
            item.setData(ID_ROLE, other)
            self.dependencies_list.addItem(item)
        self.dependency_combo.clear()
        for task in vm.tasks:
            if vm.task and task["id"] != vm.task["id"] and task["id"] not in waits_on:
                self.dependency_combo.addItem(task["title"], task["id"])

    def _fill_subtasks(self) -> None:
        """The open task's subtasks as tick boxes, keeping the selected one selected."""
        selected = self._selected_subtask_id()
        self.subtasks_list.clear()
        for subtask in (self.viewmodel.task or {}).get("subtasks", []):
            item = QListWidgetItem(subtask_label(subtask))
            item.setData(ID_ROLE, subtask["id"])
            item.setData(TITLE_ROLE, subtask["title"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            done = subtask["status"] == "done"
            item.setCheckState(Qt.CheckState.Checked if done else Qt.CheckState.Unchecked)
            self.subtasks_list.addItem(item)
            if subtask["id"] == selected:
                self.subtasks_list.setCurrentItem(item)
        self._fill_subtask_editor()

    def _selected_subtask(self) -> dict | None:
        """The subtask selected in the list, as the server last sent it."""
        chosen = self._selected_subtask_id()
        subtasks = (self.viewmodel.task or {}).get("subtasks", [])
        return next((s for s in subtasks if s["id"] == chosen), None)

    def _selected_subtask_id(self) -> int | None:
        """The id of the subtask selected in the list, or None."""
        item = self.subtasks_list.currentItem()
        return item.data(ID_ROLE) if item else None

    def _fill_subtask_editor(self) -> None:
        """Show the selected subtask's title, status, assignee and dates, unless the user is
        editing that same subtask (so an automatic refresh can't wipe it)."""
        subtask = self._selected_subtask()
        self.subtask_editor.setVisible(subtask is not None)
        if subtask is None:
            self._subtask_form_id = None
            self._subtask_dirty = False
            return
        if subtask["id"] == self._subtask_form_id and self._subtask_dirty:
            return
        was_filling, self._filling = self._filling, True
        try:
            self.subtask_editor.setTitle(f"Subtask: {subtask['title']}")
            self.subtask_title_input.setText(subtask["title"])
            status_index = self.subtask_status_combo.findData(subtask["status"])
            self.subtask_status_combo.setCurrentIndex(max(0, status_index))
            self.subtask_assignee_combo.clear()
            self.subtask_assignee_combo.addItem("Unassigned", None)
            team = self.viewmodel.team
            for member in team["members"] if team else []:
                self.subtask_assignee_combo.addItem(member["name"], member["id"])
            current = subtask["assignee"]["id"] if subtask["assignee"] else None
            index = self.subtask_assignee_combo.findData(current)
            self.subtask_assignee_combo.setCurrentIndex(max(0, index))
            self.subtask_start_input.set_value(parse_day(subtask["start_date"]))
            self.subtask_due_input.set_value(parse_day(subtask["due_date"]))
        finally:
            self._filling = was_filling
        self._subtask_form_id = subtask["id"]
        self._subtask_dirty = False

    def _fill_unscheduled(self) -> None:
        """Name the tasks the chart can't draw because they have no dates."""
        rows = (self.viewmodel.gantt or {}).get("unscheduled", [])
        titles = [row["title"] for row in rows if row["kind"] == "task"]
        self.unscheduled_label.setText(
            "Not on the chart (no dates yet): " + ", ".join(titles) if titles else ""
        )
        self.unscheduled_label.setVisible(bool(titles))

    def _apply_permissions(self) -> None:
        """Show only the actions your role allows."""
        self._apply_read_only()
        vm = self.viewmodel
        team = vm.team
        manages = team is not None and permissions.can_manage_projects(vm.me, team)
        self.project_manage_panel.setVisible(manages)
        for widget in (
            self.rename_project_input,
            self.rename_project_button,
            self.complete_project_button,
            self.delete_project_button,
        ):
            widget.setVisible(manages and vm.project is not None)
        can_delete = team is not None and permissions.can_delete_tasks(vm.me, team)
        self.delete_task_button.setVisible(can_delete and vm.task is not None)
        self.delete_subtask_button.setVisible(can_delete)
        self.saved_task_panel.setVisible(vm.task is not None)

    def _set_busy(self, busy: bool) -> None:
        """Disable the controls while a request is in flight."""
        for widget in [*self._buttons, self.team_combo, self.projects_list, self.tasks_table]:
            widget.setEnabled(not busy)
        self._apply_read_only()

    @property
    def read_only(self) -> bool:
        """True when the chosen project is completed, so its work can't be changed."""
        project = self.viewmodel.project
        return project is not None and project["status"] == "completed"

    def _apply_read_only(self) -> None:
        """Grey out every way of changing a completed project's work (the server
        refuses those changes anyway), and say why. Tasks stay viewable."""
        read_only = self.read_only
        self.editor_box.setEnabled(not read_only)
        self.new_task_button.setEnabled(not read_only and not self.viewmodel.busy)
        vm = self.viewmodel
        manages = vm.team is not None and permissions.can_manage_projects(vm.me, vm.team)
        self.read_only_label.setText(
            "This project is completed, so its tasks can't be changed. "
            + (
                "Reopen it on the left to make changes."
                if manages
                else "Ask the team lead to reopen it."
            )
            if read_only
            else ""
        )
        self.read_only_label.setVisible(read_only)

    def _keep_unsaved_edits(self, _message: str) -> None:
        """A save was refused because someone else saved first: keep what the
        user typed in the editors (the reload that follows would otherwise
        replace it with the other person's version)."""
        if self._form_task is not None:
            self._form_dirty = True
        if self._subtask_form_id is not None:
            self._subtask_dirty = True

    def _mark_subtask_dirty(self, *_args) -> None:
        """The user changed the subtask editor (ignored while the screen refills it)."""
        if not self._filling:
            self._subtask_dirty = True

    def _mark_dirty(self, *_args) -> None:
        """The user changed an editor field (ignored while the screen refills it)."""
        if not self._filling:
            self._form_dirty = True

    # ------------------------------------------------------------ actions

    def _on_team_chosen(self, index: int) -> None:
        """The user picked another team."""
        if not self._filling and index >= 0:
            self.viewmodel.select_team(self.team_combo.itemData(index))

    def _on_project_clicked(self, current: QListWidgetItem | None, _previous) -> None:
        """The user picked a project in the list."""
        if not self._filling and current is not None:
            self.viewmodel.select_project(current.data(ID_ROLE))

    def _create_project(self) -> None:
        """Create a project from the name box; clear the box once accepted."""
        self.viewmodel.create_project(self.new_project_input.text())
        if self.viewmodel.busy:
            self.new_project_input.clear()

    def _rename_project(self) -> None:
        """Rename the chosen project to what is in the rename box."""
        self.viewmodel.rename_project(self.rename_project_input.text())
        self.rename_project_input.setModified(False)

    def _toggle_project_completed(self) -> None:
        """Complete the chosen project, or reopen it."""
        project = self.viewmodel.project
        if project is not None:
            self.viewmodel.set_project_completed(project["status"] != "completed")

    def _delete_project(self) -> None:
        """After confirming, delete the chosen project and its tasks."""
        project = self.viewmodel.project
        if project and self.confirm(
            "Delete project",
            f"Delete {project['name']} and all of its tasks? This can't be undone.",
        ):
            self.viewmodel.delete_project()

    def _on_only_mine_toggled(self, _checked: bool) -> None:
        """Re-show the task list with or without the "Only my work" filter."""
        was_filling, self._filling = self._filling, True
        try:
            self._fill_tasks()
        finally:
            self._filling = was_filling

    def _on_task_clicked(self) -> None:
        """The user picked a task in the table: open it in the editor."""
        if self._filling:
            return
        items = self.tasks_table.selectedItems()
        if items:
            self.viewmodel.select_task(items[0].data(ID_ROLE))

    def _open_task_from_chart(self, task_id: int) -> None:
        """A Gantt bar was clicked: open that task on the Tasks tab."""
        self.tabs.setCurrentIndex(0)
        self.viewmodel.select_task(task_id)

    def _start_new_task(self) -> None:
        """Clear the editor for a new task."""
        self._filling = True
        try:
            self.tasks_table.clearSelection()
            self._load_form(None)
            self._fill_assignees(keep_choice=False)
        finally:
            self._filling = False
        self._form_task = NEW_TASK
        self._form_dirty = False
        self.viewmodel.select_task(None)
        self.title_input.setFocus()

    def form_fields(self) -> dict:
        """The editor's values, as the view model takes them."""
        return {
            "title": self.title_input.text(),
            "description": self.description_input.toPlainText(),
            "assignee_id": self.assignee_combo.currentData(),
            "start_date": self.start_input.value(),
            "due_date": self.due_input.value(),
            "status": self.status_combo.currentData(),
        }

    def _save_task(self) -> None:
        """Create the new task, or save changes to the open one."""
        fields = self.form_fields()
        if self.viewmodel.task is None:
            self.viewmodel.create_task(fields)
        else:
            self.viewmodel.save_task(fields)
        if self.viewmodel.busy:  # accepted: the reload may refill the editor
            self._form_dirty = False

    def _delete_task(self) -> None:
        """After confirming, delete the open task."""
        task = self.viewmodel.task
        if task and self.confirm("Delete task", f"Delete {task['title']} and its subtasks?"):
            self.viewmodel.delete_task()

    def _add_dependency(self) -> None:
        """Make the open task wait on the task chosen in the picker."""
        other = self.dependency_combo.currentData()
        if other is not None:
            self.viewmodel.add_dependency(other)

    def _remove_dependency(self) -> None:
        """Stop the open task waiting on the selected task."""
        item = self.dependencies_list.currentItem()
        if item is not None:
            self.viewmodel.remove_dependency(item.data(ID_ROLE))

    def _add_subtask(self) -> None:
        """Add a subtask from the box; clear the box once accepted."""
        self.viewmodel.add_subtask(self.subtask_input.text())
        if self.viewmodel.busy:
            self.subtask_input.clear()

    def _on_subtask_ticked(self, item: QListWidgetItem) -> None:
        """A subtask box was ticked or unticked."""
        if not self._filling:
            done = item.checkState() == Qt.CheckState.Checked
            self.viewmodel.set_subtask_done(item.data(ID_ROLE), done)

    def _on_subtask_selected(self, *_args) -> None:
        """A different subtask was picked: show it in the editor."""
        if not self._filling:
            self._subtask_dirty = False
            self._fill_subtask_editor()

    def _save_subtask(self) -> None:
        """Save the editor's title, status, assignee and dates to the selected subtask."""
        subtask_id = self._selected_subtask_id()
        if subtask_id is None:
            return
        self.viewmodel.save_subtask(
            subtask_id,
            title=self.subtask_title_input.text(),
            status=self.subtask_status_combo.currentData(),
            assignee_id=self.subtask_assignee_combo.currentData(),
            start_date=self.subtask_start_input.value(),
            due_date=self.subtask_due_input.value(),
        )
        if self.viewmodel.busy:  # accepted: let the reload refill the editor
            self._subtask_dirty = False

    def _delete_subtask(self) -> None:
        """After confirming, delete the selected subtask."""
        item = self.subtasks_list.currentItem()
        if item and self.confirm("Delete subtask", f"Delete {item.data(TITLE_ROLE)}?"):
            self.viewmodel.delete_subtask(item.data(ID_ROLE))

    #: Set by the home screen when its offline banner already reports
    #: "can't reach the server", so this screen doesn't say it a second time.
    connection_errors_shown_elsewhere = False

    def _show_error(self, message: str) -> None:
        """Show an error, unless it is a connection error the offline banner already shows."""
        if self.connection_errors_shown_elsewhere and is_connection_error(message):
            message = ""
        self.error_label.show_message(message)
