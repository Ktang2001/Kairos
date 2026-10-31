"""The Profile tab: how you join meetings and when you're reminded of them,
saved on this computer.

Kairos can't hold a Jitsi account or sign you in to one: meet.jit.si signs
people in with Google, GitHub or Facebook on its own site. What this page can
do is fill in your name and join options on every meeting link, and open the
Jitsi site so you can sign in there once -- your browser then remembers it,
so later meetings open already signed in.
"""

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.viewmodels.meeting_preferences import MAX_MEETING_NAME_LENGTH, MeetingPreferences
from client.viewmodels.meetings_viewmodel import MeetingsViewModel
from client.views.widgets import ErrorLabel
from shared.meetings import PROFILE_REMINDER_CHOICES, reminder_label

SIGN_IN_EXPLANATION = (
    "Meetings open in your web browser on Jitsi. Jitsi asks whoever opens a "
    "meeting room first to sign in (with Google, GitHub or Facebook) - that "
    "person becomes the meeting's moderator, who can mute people, turn on the "
    "lobby or kick someone out. Kairos never sees that sign-in. Sign in once "
    "below and your browser remembers it for later meetings."
)


class ProfilePage(QWidget):
    """Your meeting name and join options, plus a way to sign in to Jitsi ahead of time."""

    def __init__(
        self,
        preferences: MeetingPreferences,
        meetings: MeetingsViewModel,
        kairos_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.preferences = preferences
        self.meetings = meetings

        self.name_input = QLineEdit(preferences.display_name)
        self.name_input.setMaxLength(MAX_MEETING_NAME_LENGTH)
        self.name_input.setPlaceholderText(kairos_name or "Your name")
        self.muted_box = QCheckBox("Join with my microphone muted")
        self.muted_box.setChecked(preferences.start_muted)
        self.camera_box = QCheckBox("Join with my camera off")
        self.camera_box.setChecked(preferences.camera_off)
        #: Your default reminder for every meeting (None = Off). Hosts can add
        #: more for a meeting; a time in both reminds you once.
        self.reminder_input = QComboBox()
        self.reminder_input.addItem("Off", None)
        for minutes in PROFILE_REMINDER_CHOICES:
            self.reminder_input.addItem(reminder_label(minutes), minutes)
        self.reminder_input.setCurrentIndex(
            max(0, self.reminder_input.findData(preferences.reminder_minutes))
        )

        form = QFormLayout()
        form.addRow("Name in meetings:", self.name_input)
        form.addRow(self.muted_box)
        form.addRow(self.camera_box)
        form.addRow("Remind me:", self.reminder_input)
        options = QGroupBox("Joining meetings")
        options.setLayout(form)

        self.explanation = QLabel(SIGN_IN_EXPLANATION)
        self.explanation.setWordWrap(True)
        self.sign_in_button = QPushButton("Sign in to Jitsi...")
        sign_in_layout = QVBoxLayout()
        sign_in_layout.addWidget(self.explanation)
        sign_in_layout.addWidget(self.sign_in_button)
        sign_in = QGroupBox("Jitsi account")
        sign_in.setLayout(sign_in_layout)

        self.saved_label = QLabel("")
        self.saved_label.setProperty("muted", True)
        self.error_label = ErrorLabel()

        layout = QVBoxLayout(self)
        layout.addWidget(options)
        layout.addWidget(sign_in)
        layout.addWidget(self.saved_label)
        layout.addWidget(self.error_label)
        layout.addStretch()

        # Saved as soon as they change: there is nothing to submit to a server.
        self.name_input.editingFinished.connect(self._save_name)
        self.muted_box.toggled.connect(self._save_muted)
        self.camera_box.toggled.connect(self._save_camera)
        self.reminder_input.currentIndexChanged.connect(self._save_reminder)
        self.sign_in_button.clicked.connect(meetings.open_jitsi_home)
        meetings.error_changed.connect(self._show_error)

    def _save_name(self) -> None:
        self.preferences.display_name = self.name_input.text()
        self.name_input.setText(self.preferences.display_name)
        self._saved()

    def _save_muted(self, checked: bool) -> None:
        self.preferences.start_muted = checked
        self._saved()

    def _save_camera(self, checked: bool) -> None:
        self.preferences.camera_off = checked
        self._saved()

    def _save_reminder(self, _index: int) -> None:
        self.preferences.reminder_minutes = self.reminder_input.currentData()
        self._saved()

    def _saved(self) -> None:
        self.saved_label.setText("Saved on this computer.")

    def _show_error(self, message: str) -> None:
        # Shared view model: only show what happened while this page is showing.
        if self.isVisible():
            self.error_label.show_message(message)
