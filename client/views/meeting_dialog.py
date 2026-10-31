"""The "New meeting" dialog: what, start now or when, how long, reminders for
everyone, and (from the Dashboard) for which team.

Times are picked in this computer's local time and sent with its offset, so
the server -- possibly on a computer set to another time zone -- stores the
right moment. The server checks everything again.
"""

import uuid
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QDateTime, QTime
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from client.views.meeting_card import zone_name
from client.views.widgets import ErrorLabel
from shared.meetings import (
    DEFAULT_DURATION_MINUTES,
    MAX_DURATION_MINUTES,
    MAX_MEETING_TITLE_LENGTH,
    MIN_DURATION_MINUTES,
    PAST_START_GRACE,
    REMINDER_CHOICES,
    reminder_label,
)
from shared.text_rules import clean_display_text


def _next_half_hour(now: datetime) -> datetime:
    """The first :00 or :30 after ``now`` -- a sensible default start."""
    start = now.replace(second=0, microsecond=0) + timedelta(minutes=1)
    return start + timedelta(minutes=(30 - start.minute % 30) % 30)


class NewMeetingDialog(QDialog):
    """Ask for a meeting's details. After ``exec()`` returns Accepted, read the
    ``result_*`` attributes.

    With ``teams``, a "Team" picker is shown and ``result_team_id`` is set.
    With ``meeting`` (a MeetingOut), it edits that meeting instead: filled in
    with its details, and always scheduled (there is no "start now").
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        teams: list[dict] | None = None,
        team_id: int | None = None,
        default_title: str = "",
        meeting: dict | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New meeting")

        self.title_input = QLineEdit(default_title)
        self.title_input.setMaxLength(MAX_MEETING_TITLE_LENGTH)
        self.title_input.setPlaceholderText("e.g. Weekly stand-up")

        self.team_input = QComboBox()
        for team in teams or []:
            self.team_input.addItem(team["name"], team["id"])
            if team["id"] == team_id:
                self.team_input.setCurrentIndex(self.team_input.count() - 1)

        self.now_option = QRadioButton("Start now")
        self.schedule_option = QRadioButton("Schedule for")
        self.now_option.setChecked(True)
        start = _next_half_hour(datetime.now())  # local time, like the picker
        self.when_input = QDateTimeEdit(
            QDateTime(QDate(start.year, start.month, start.day), QTime(start.hour, start.minute))
        )
        self.when_input.setCalendarPopup(True)
        self.when_input.setDisplayFormat("ddd d MMM yyyy  h:mm AP")
        self.when_input.setEnabled(False)
        self.schedule_option.toggled.connect(self.when_input.setEnabled)

        self.duration_input = QSpinBox()
        self.duration_input.setRange(MIN_DURATION_MINUTES, MAX_DURATION_MINUTES)
        self.duration_input.setSingleStep(15)
        self.duration_input.setValue(DEFAULT_DURATION_MINUTES)
        self.duration_input.setSuffix(" min")

        #: Times are picked in this computer's zone; say which, since the
        #: people invited may be in another (each of them sees their own).
        self.zone_label = QLabel(f"Your time zone: {zone_name(datetime.now().astimezone())}")
        self.zone_label.setProperty("muted", True)
        self.zone_label.setEnabled(False)
        self.schedule_option.toggled.connect(self.zone_label.setEnabled)

        #: Reminders for everyone invited, on top of each person's own default
        #: (their Profile page). Only for a scheduled meeting.
        self.reminder_boxes: dict[int, QCheckBox] = {}
        self.reminders_group = QGroupBox("Remind everyone (on top of their own default)")
        reminders_grid = QGridLayout(self.reminders_group)
        for index, minutes in enumerate(REMINDER_CHOICES):
            box = QCheckBox(reminder_label(minutes))
            self.reminder_boxes[minutes] = box
            reminders_grid.addWidget(box, index // 4, index % 4)
        self.reminders_group.setEnabled(False)
        self.schedule_option.toggled.connect(self.reminders_group.setEnabled)

        form = QFormLayout()
        form.addRow("Title:", self.title_input)
        if teams is not None:
            form.addRow("Team:", self.team_input)
        form.addRow(self.now_option)
        form.addRow(self.schedule_option, self.when_input)
        form.addRow("", self.zone_label)
        form.addRow("Length:", self.duration_input)

        self.error_label = ErrorLabel()
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._on_accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.reminders_group)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

        self._has_team_picker = teams is not None
        self.result_title = ""
        #: Time-zone aware, or None for "start now".
        self.result_starts_at: datetime | None = None
        self.result_duration_minutes = DEFAULT_DURATION_MINUTES
        self.result_team_id: int | None = None
        #: The host's reminders for everyone, minutes before the start.
        self.result_reminder_minutes: list[int] = []
        #: Sent with the request so a retry can't make the meeting twice.
        self.result_client_token = uuid.uuid4().hex

        #: The start being edited (local, to the minute); a meeting already
        #: under way may keep it even though it has passed.
        self._original_start: datetime | None = None
        if meeting is not None:
            self._fill_from(meeting)

    def _fill_from(self, meeting: dict) -> None:
        """Show an existing meeting's details, in this computer's time zone."""
        self.setWindowTitle("Edit meeting")
        self.title_input.setText(meeting["title"])
        start = datetime.fromisoformat(meeting["starts_at"]).astimezone()
        start = start.replace(second=0, microsecond=0)
        self._original_start = start
        self.schedule_option.setChecked(True)
        self.now_option.setVisible(False)
        self.when_input.setDateTime(
            QDateTime(QDate(start.year, start.month, start.day), QTime(start.hour, start.minute))
        )
        self.duration_input.setValue(meeting["duration_minutes"])
        for minutes, box in self.reminder_boxes.items():
            box.setChecked(minutes in (meeting.get("reminder_minutes") or []))

    def _on_accept(self) -> None:
        title = clean_display_text(self.title_input.text())
        if not title:
            self.error_label.show_message("Give the meeting a title.")
            return
        if self._has_team_picker and self.team_input.currentData() is None:
            self.error_label.show_message("You're not on any teams yet - pick a chat instead.")
            return

        starts_at = None
        if self.schedule_option.isChecked():
            # toPython() is the picker's local wall-clock time; astimezone()
            # attaches this computer's offset for that date (summer or winter).
            starts_at = self.when_input.dateTime().toPython().astimezone()
            unchanged = starts_at == self._original_start
            if not unchanged and starts_at < datetime.now().astimezone() - PAST_START_GRACE:
                self.error_label.show_message("That time has already passed.")
                return

        self.result_title = title
        self.result_starts_at = starts_at
        self.result_duration_minutes = self.duration_input.value()
        self.result_team_id = self.team_input.currentData() if self._has_team_picker else None
        self.result_reminder_minutes = (
            sorted(minutes for minutes, box in self.reminder_boxes.items() if box.isChecked())
            if starts_at is not None
            else []
        )
        self.accept()


def edit_meeting(parent: QWidget, meetings, meeting: dict) -> None:
    """Ask for a meeting's new details and save them through ``meetings``
    (a MeetingsViewModel). Shared by the chat cards and the Dashboard."""
    dialog = NewMeetingDialog(parent, meeting=meeting)
    if dialog.exec() != NewMeetingDialog.DialogCode.Accepted:
        return
    meetings.edit(
        meeting["id"],
        title=dialog.result_title,
        starts_at=dialog.result_starts_at,
        duration_minutes=dialog.result_duration_minutes,
        reminder_minutes=dialog.result_reminder_minutes,
    )
