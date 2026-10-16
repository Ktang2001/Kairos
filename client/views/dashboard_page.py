"""The Dashboard (context.md goal #7): a clock, four figures, a calendar with
your deadlines marked, and lists of what's due and how each project is going.

Built from GET /dashboard through ``DashboardViewModel``. Without a view model
(as in some tests) the page shows its empty states and makes no requests.
"""

from datetime import date

from PySide6.QtCore import QDate, QDateTime, QTimer
from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from client.viewmodels.dashboard_viewmodel import DashboardViewModel
from client.views.widgets import ErrorLabel

#: Background for days with one of your deadlines: a translucent red, so the
#: day number stays readable on light and dark themes. A background rather than
#: red text, because the calendar already draws weekend numbers in red.
DEADLINE_BACKGROUND = QColor(229, 72, 77, 90)


class _StatTile(QWidget):
    """A small 'N over label' tile, e.g. the top summary row. Value starts as a
    placeholder dash - call set_value() once real data exists.
    """

    def __init__(self, label: str) -> None:
        super().__init__()
        self.value_label = QLabel("—")
        self.value_label.setObjectName("statValue")
        caption = QLabel(label)
        caption.setProperty("muted", True)

        layout = QVBoxLayout()
        layout.setAlignment(caption.alignment())
        layout.addWidget(self.value_label)
        layout.addWidget(caption)
        self.setLayout(layout)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class ClockWidget(QWidget):
    """A live date/time display, refreshed every second."""

    def __init__(self) -> None:
        super().__init__()
        self.time_label = QLabel()
        self.time_label.setObjectName("clockTime")
        self.date_label = QLabel()
        self.date_label.setProperty("muted", True)

        layout = QVBoxLayout()
        layout.addWidget(self.time_label)
        layout.addWidget(self.date_label)
        self.setLayout(layout)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()
        self._refresh()

    def _refresh(self) -> None:
        now = QDateTime.currentDateTime()
        self.time_label.setText(now.toString("h:mm:ss AP"))
        self.date_label.setText(now.toString("dddd, MMMM d, yyyy"))


class _ListPanel(QGroupBox):
    """A titled, empty-state list panel (Due Dates / Tasks / Meetings / ...).

    Pure presentation - add_item()/set_items()/clear_items() are the extension
    points for whoever wires up real project/task data later.
    """

    def __init__(self, title: str, empty_text: str) -> None:
        super().__init__(title)
        self._empty_text = empty_text

        self.list_widget = QListWidget()
        layout = QVBoxLayout()
        layout.addWidget(self.list_widget)
        self.setLayout(layout)

        self._show_empty_state()

    def _show_empty_state(self) -> None:
        self.list_widget.clear()
        self.list_widget.addItem(self._empty_text)

    def set_items(self, items: list[str]) -> None:
        self.list_widget.clear()
        if not items:
            self._show_empty_state()
            return
        for item in items:
            self.list_widget.addItem(item)


def _short(day: str | None) -> str:
    """An API date as "Nov 02"."""
    return date.fromisoformat(day).strftime("%b %d") if day else ""


class DashboardPage(QWidget):
    """The Dashboard tab. Display only; DashboardViewModel holds the data."""

    def __init__(self, viewmodel: DashboardViewModel | None = None) -> None:
        super().__init__()
        self.viewmodel = viewmodel

        self.clock = ClockWidget()

        self.stat_tasks = _StatTile("My Open Tasks")
        self.stat_projects = _StatTile("Active Projects")
        self.stat_due_soon = _StatTile("Due Soon")
        self.stat_overdue = _StatTile("Overdue")

        stats_row = QHBoxLayout()
        stats_row.addWidget(self.clock)
        stats_row.addStretch()
        for tile in (self.stat_tasks, self.stat_projects, self.stat_due_soon, self.stat_overdue):
            stats_row.addWidget(tile)

        self.calendar = QCalendarWidget()
        #: Days marked on the calendar, so the next load can unmark them.
        self._marked_days: list[QDate] = []

        self.due_dates_panel = _ListPanel("My Deadlines", "No due dates yet.")
        self.tasks_panel = _ListPanel("Project Progress", "No tasks or projects yet.")
        self.meetings_panel = _ListPanel("Meetings", "No meetings scheduled yet.")

        panels_column = QVBoxLayout()
        panels_column.addWidget(self.due_dates_panel)
        panels_column.addWidget(self.tasks_panel)
        panels_column.addWidget(self.meetings_panel)

        main_row = QHBoxLayout()
        main_row.addWidget(self.calendar, stretch=2)
        panels_widget = QWidget()
        panels_widget.setLayout(panels_column)
        main_row.addWidget(panels_widget, stretch=1)

        self.as_of_label = QLabel()
        self.as_of_label.setProperty("muted", True)
        self.error_label = ErrorLabel()

        layout = QVBoxLayout()
        layout.addLayout(stats_row)
        layout.addLayout(main_row)
        layout.addWidget(self.as_of_label)
        layout.addWidget(self.error_label)
        self.setLayout(layout)

        if viewmodel is not None:
            viewmodel.loaded.connect(self.show_data)
            viewmodel.error_changed.connect(self.error_label.show_message)
            if viewmodel.data is not None:
                self.show_data(viewmodel.data)

    def refresh(self) -> None:
        """Reload the figures (no-op without a view model)."""
        if self.viewmodel is not None:
            self.viewmodel.refresh()

    def show_data(self, data: dict) -> None:
        """Fill every tile, list and calendar mark from a /dashboard response."""
        mine, overview = data["my_work"], data["overview"]
        self.stat_tasks.set_value(str(mine["open"]))
        self.stat_projects.set_value(str(overview["active_projects"]))
        self.stat_due_soon.set_value(str(mine["due_soon"]))
        self.stat_overdue.set_value(str(mine["overdue"]))

        today = data["today"]
        deadlines = []
        for task in mine["upcoming"]:
            late = "OVERDUE - " if task["due_date"] < today else ""
            deadlines.append(
                f"{late}{_short(task['due_date'])}: {task['title']} ({task['project_name']})"
            )
        self.due_dates_panel.set_items(deadlines)

        progress = []
        for project in data["projects"]:
            line = (
                f"{project['name']} ({project['team_name']}): {project['percent_complete']:g}% done"
            )
            if project["overdue"]:
                line += f", {project['overdue']} overdue"
            if project["status"] == "completed":
                line += " [completed]"
            progress.append(line)
        self.tasks_panel.set_items(progress)

        self._mark_deadlines([task["due_date"] for task in mine["upcoming"]])
        self.as_of_label.setText(
            f'Figures as of {_short(today)}. "Due soon" means within '
            f"{data['due_soon_days']} days. Your deadlines are shaded on the calendar."
        )

    def _mark_deadlines(self, days: list[str]) -> None:
        """Shade each day with one of your deadlines and make it bold; unmark the old ones."""
        for day in self._marked_days:
            self.calendar.setDateTextFormat(day, QTextCharFormat())
        mark = QTextCharFormat()
        mark.setBackground(DEADLINE_BACKGROUND)
        mark.setFontWeight(QFont.Weight.Bold)
        self._marked_days = []
        for value in days:
            day = date.fromisoformat(value)
            qdate = QDate(day.year, day.month, day.day)
            self.calendar.setDateTextFormat(qdate, mark)
            self._marked_days.append(qdate)
