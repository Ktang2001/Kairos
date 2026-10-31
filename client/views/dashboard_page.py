"""The Dashboard (context.md goal #7): a clock, five figures, a calendar with
your deadlines and meetings marked, lists of what's due and how each project
is going, and your upcoming meetings with Join buttons.

Built from GET /dashboard through ``DashboardViewModel``. Without a view model
(as in some tests) the page shows its empty states and makes no requests.
Meeting actions go through the window's shared ``MeetingsViewModel``; without
one the meeting cards are shown but the "New meeting" button is hidden.
"""

from collections.abc import Callable
from datetime import date, datetime

from PySide6.QtCore import QDate, QDateTime, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QTextCharFormat
from PySide6.QtWidgets import (
    QCalendarWidget,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from client.viewmodels.dashboard_viewmodel import DashboardViewModel
from client.viewmodels.meetings_viewmodel import MeetingsViewModel
from client.views.meeting_card import MeetingsPanel, meeting_day
from client.views.meeting_dialog import NewMeetingDialog, edit_meeting
from client.views.teams_view import ask_yes_no
from client.views.time_text import (
    clock,
    due_day,
    due_moment,
    is_past_due,
    local,
    show_due,
    zone_name,
)
from client.views.widgets import ErrorLabel

#: Background for days with one of your deadlines: a translucent red, so the
#: day number stays readable on light and dark themes. A background rather than
#: red text, because the calendar already draws weekend numbers in red.
DEADLINE_BACKGROUND = QColor(229, 72, 77, 90)
#: Background for days with a meeting: a translucent blue, for the same reason.
MEETING_BACKGROUND = QColor(59, 130, 246, 90)
#: A day with both: purple, the two mixed.
DEADLINE_AND_MEETING_BACKGROUND = QColor(147, 88, 214, 110)


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

    def __init__(
        self,
        viewmodel: DashboardViewModel | None = None,
        meetings: MeetingsViewModel | None = None,
    ) -> None:
        super().__init__()
        self.viewmodel = viewmodel
        self.meetings = meetings
        #: Asks the user to confirm cancelling a meeting. Replaced in tests.
        self.confirm: Callable[[str, str], bool] = lambda title, question: ask_yes_no(
            self, title, question
        )

        self.clock = ClockWidget()

        self.stat_tasks = _StatTile("My Open Work")
        self.stat_projects = _StatTile("Active Projects")
        self.stat_due_soon = _StatTile("Due Soon")
        self.stat_overdue = _StatTile("Overdue")
        self.stat_meetings = _StatTile("Meetings")

        stats_row = QHBoxLayout()
        stats_row.addWidget(self.clock)
        stats_row.addStretch()
        for tile in (
            self.stat_tasks,
            self.stat_projects,
            self.stat_due_soon,
            self.stat_overdue,
            self.stat_meetings,
        ):
            stats_row.addWidget(tile)

        self.calendar = QCalendarWidget()
        # The month arrows are black icons, nearly invisible on the dark
        # theme; text arrows take the theme's text colour instead.
        for name, arrow in (("qt_calendar_prevmonth", "‹"), ("qt_calendar_nextmonth", "›")):
            button = self.calendar.findChild(QToolButton, name)
            if button is not None:
                button.setIcon(QIcon())
                button.setText(arrow)
                # Sized in light.qss / dark.qss: the theme's font-size wins over setFont.
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        #: Days marked on the calendar, so the next load can unmark them.
        self._marked_days: list[QDate] = []

        self.due_dates_panel = _ListPanel("My Deadlines", "No due dates yet.")
        self.tasks_panel = _ListPanel("Project Progress", "No tasks or projects yet.")
        self.meetings_panel = MeetingsPanel("Upcoming Meetings", "No upcoming meetings.")
        self.new_meeting_button = QPushButton("New meeting...")
        self.new_meeting_button.setToolTip(
            "Start or schedule a Jitsi meeting for one of your teams"
        )
        self.meetings_panel.header.addStretch()
        self.meetings_panel.header.addWidget(self.new_meeting_button)
        self.new_meeting_button.setVisible(meetings is not None)

        panels_column = QVBoxLayout()
        panels_column.addWidget(self.due_dates_panel, stretch=1)
        panels_column.addWidget(self.tasks_panel, stretch=1)
        # Cards are taller than list lines: give the meetings the most room.
        panels_column.addWidget(self.meetings_panel, stretch=2)

        main_row = QHBoxLayout()
        #: What is on the day picked in the calendar (today to begin with): a
        #: marked day's colour is hidden while that day is selected, and the
        #: calendar can't show what a mark stands for.
        self.day_label = QLabel()
        self.day_label.setTextFormat(Qt.TextFormat.PlainText)  # titles came from people
        self.day_label.setWordWrap(True)
        #: Lines for each marked day: (sort key, text).
        self._day_items: dict[date, list[tuple[str, str]]] = {}
        self.calendar.selectionChanged.connect(self._show_selected_day)
        calendar_column = QVBoxLayout()
        calendar_column.addWidget(self.calendar, stretch=1)
        calendar_column.addWidget(self.day_label)
        main_row.addLayout(calendar_column, stretch=2)
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

        if meetings is not None:
            self.new_meeting_button.clicked.connect(self._on_new_meeting)
            self.meetings_panel.respond_clicked.connect(meetings.respond)
            self.meetings_panel.join_clicked.connect(meetings.join)
            self.meetings_panel.edit_clicked.connect(self._edit_meeting)
            self.meetings_panel.cancel_clicked.connect(self._confirm_cancel)
            meetings.meeting_changed.connect(lambda _meeting: self.refresh())
            meetings.busy_changed.connect(self._set_meetings_busy)
            meetings.error_changed.connect(self._show_meeting_error)

    def refresh(self) -> None:
        """Reload the figures (no-op without a view model)."""
        if self.viewmodel is not None:
            self.viewmodel.refresh()

    def show_data(self, data: dict) -> None:
        """Fill every tile, list and calendar mark from a /dashboard response."""
        mine, overview = data["my_work"], data["overview"]
        # Subtasks assigned to you count as your work too (goal 4). ``get``:
        # a server from before subtask figures existed simply sends none.
        subtasks = mine.get("upcoming_subtasks", [])
        self.stat_tasks.set_value(str(mine["open"] + mine.get("subtasks_open", 0)))
        self.stat_projects.set_value(str(overview["active_projects"]))
        self.stat_due_soon.set_value(str(mine["due_soon"] + mine.get("subtasks_due_soon", 0)))
        self.stat_overdue.set_value(str(mine["overdue"] + mine.get("subtasks_overdue", 0)))
        # ``get``: a server from before meetings existed sends none.
        meetings = data.get("meetings", [])
        self.stat_meetings.set_value(str(overview.get("upcoming_meetings", len(meetings))))
        self.meetings_panel.set_meetings(meetings)

        today = data["today"]
        # Each deadline in this computer's time zone, overdue by its exact
        # time (``is_past_due``), soonest first.
        dated = [(task, f"{task['title']} ({task['project_name']})") for task in mine["upcoming"]]
        dated += [
            (s, f"{s['title']} (subtask of {s['task_title']}, {s['project_name']})")
            for s in subtasks
        ]
        dated.sort(key=lambda pair: (due_day(pair[0]), due_moment(pair[0]) is None, pair[1]))
        # A deadline without an exact time (from an older server) is judged by
        # the day the server's figures are for, as before.
        now, server_today = datetime.now().astimezone(), date.fromisoformat(today)
        deadlines = []
        for item, what in dated:
            late = "OVERDUE - " if is_past_due(item, now, server_today) else ""
            deadlines.append(f"{late}{show_due(item, year=False)}: {what}")
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

        self._mark_days(
            [due_day(item) for item, _what in dated],
            [meeting_day(meeting) for meeting in meetings],
        )
        self._list_days(dated, meetings)
        self.as_of_label.setText(
            f'Figures as of {_short(today)}. "Due soon" means within '
            f"{data['due_soon_days']} days. On the calendar, your deadlines are red, "
            "meetings blue, and days with both purple."
        )

    def _list_days(self, dated: list[tuple[dict, str]], meetings: list[dict]) -> None:
        """Remember what is on each day (in this computer's zone), for ``day_label``."""
        self._day_items = {}
        for item, what in dated:
            moment = due_moment(item)
            when = f"{clock(moment)} {zone_name(moment)}" if moment else "end of day"
            key = moment.isoformat() if moment else "~"  # dated-only last
            self._day_items.setdefault(due_day(item), []).append((key, f"Due {when}: {what}"))
        for meeting in meetings:
            start = local(meeting["starts_at"])
            text = f"Meeting {clock(start)} {zone_name(start)}: {meeting['title']}"
            self._day_items.setdefault(start.date(), []).append((start.isoformat(), text))
        self._show_selected_day()

    def _show_selected_day(self) -> None:
        """List what is due and which meetings are on the day picked in the calendar."""
        day = self.calendar.selectedDate().toPython()
        items = [text for _key, text in sorted(self._day_items.get(day, []))]
        heading = f"{day:%a, %b %d}"
        self.day_label.setText(
            f"{heading}: " + ("; ".join(items) if items else "nothing due, no meetings.")
        )

    def _mark_days(self, deadlines: list[date], meeting_days: list[date]) -> None:
        """Shade each day with one of your deadlines (red), a meeting (blue) or
        both (purple), in bold; unmark the old ones.

        A day has one format, so a day with both gets the mixed colour rather
        than one mark replacing the other.
        """
        for day in self._marked_days:
            self.calendar.setDateTextFormat(day, QTextCharFormat())
        deadline_days, meeting_set = set(deadlines), set(meeting_days)
        self._marked_days = []
        for day in sorted(deadline_days | meeting_set):
            mark = QTextCharFormat()
            if day in deadline_days and day in meeting_set:
                mark.setBackground(DEADLINE_AND_MEETING_BACKGROUND)
            elif day in deadline_days:
                mark.setBackground(DEADLINE_BACKGROUND)
            else:
                mark.setBackground(MEETING_BACKGROUND)
            mark.setFontWeight(QFont.Weight.Bold)
            qdate = QDate(day.year, day.month, day.day)
            self.calendar.setDateTextFormat(qdate, mark)
            self._marked_days.append(qdate)

    # ------------------------------------------------------------- meetings

    def _on_new_meeting(self) -> None:
        """Fetch your teams, then ask which one the meeting is for and when."""
        if self.meetings is not None:
            self.meetings.load_teams(self._ask_for_team_meeting)

    def _ask_for_team_meeting(self, teams: list[dict]) -> None:
        # Admins are sent every team, but a team meeting is held in the team's
        # chat, which only its members are in. (``get``: older servers.)
        teams = [team for team in teams if team.get("is_member", True)]
        if not teams:
            self.error_label.show_message(
                "You're not on any teams yet - start a meeting from a chat instead."
            )
            return
        dialog = NewMeetingDialog(self, teams=teams)
        if dialog.exec() != NewMeetingDialog.DialogCode.Accepted:
            return
        self.meetings.create_for_team(
            dialog.result_team_id,
            title=dialog.result_title,
            starts_at=dialog.result_starts_at,
            duration_minutes=dialog.result_duration_minutes,
            client_token=dialog.result_client_token,
            reminder_minutes=dialog.result_reminder_minutes,
        )

    def _edit_meeting(self, meeting_id: int) -> None:
        card = self.meetings_panel.cards.get(meeting_id)
        if card is not None and self.meetings is not None:
            edit_meeting(self, self.meetings, card.meeting)

    def _confirm_cancel(self, meeting_id: int) -> None:
        card = self.meetings_panel.cards.get(meeting_id)
        title = card.meeting["title"] if card is not None else "this meeting"
        if self.confirm("Cancel meeting", f'Cancel "{title}" for everyone?'):
            self.meetings.cancel(meeting_id)

    def _set_meetings_busy(self, busy: bool) -> None:
        self.new_meeting_button.setEnabled(not busy)
        self.meetings_panel.set_busy(busy)

    def _show_meeting_error(self, message: str) -> None:
        # The view model is shared with other pages: only show what happened
        # while this page is the one on screen.
        if self.isVisible():
            self.error_label.show_message(message)
