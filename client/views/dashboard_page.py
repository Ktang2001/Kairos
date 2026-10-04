from PySide6.QtCore import QDateTime, QTimer
from PySide6.QtWidgets import (
    QCalendarWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)


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


class DashboardPage(QWidget):
    """Widgets-only shell: a calendar plus due-dates/tasks/meetings panels and a
    stats row. No task/project backend exists yet (that's separate, ongoing work) -
    this page deliberately makes no network calls; it's ready for someone else to
    populate via each panel's set_items()/set_value() once that data exists.
    """

    def __init__(self) -> None:
        super().__init__()

        self.clock = ClockWidget()

        self.stat_tasks = _StatTile("Open Tasks")
        self.stat_projects = _StatTile("Projects")
        self.stat_due_soon = _StatTile("Due Soon")
        self.stat_meetings = _StatTile("Meetings")

        stats_row = QHBoxLayout()
        stats_row.addWidget(self.clock)
        stats_row.addStretch()
        for tile in (self.stat_tasks, self.stat_projects, self.stat_due_soon, self.stat_meetings):
            stats_row.addWidget(tile)

        self.calendar = QCalendarWidget()

        self.due_dates_panel = _ListPanel("Due Dates", "No due dates yet.")
        self.tasks_panel = _ListPanel("Tasks", "No tasks assigned yet.")
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

        layout = QVBoxLayout()
        layout.addLayout(stats_row)
        layout.addLayout(main_row)
        self.setLayout(layout)
