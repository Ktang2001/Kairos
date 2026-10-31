"""A meeting's card -- in a chat and in the Dashboard's Meetings list.

Shows what and when (in this computer's time zone, named), who hosts, who has
replied, and only the buttons that make sense: Accept / Tentative / Decline
for invitees, Join while it's on, Cancel for the host or an admin. A
cancelled or finished meeting shows that instead of buttons.

Titles and names came from people, so every label is plain text (see
tests/client/test_plain_text_display.py).
"""

from datetime import date

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from client.views.time_text import clock as _clock
from client.views.time_text import local as _local
from client.views.time_text import zone_name
from client.views.widgets import ElidedLabel
from shared.meetings import (
    MEETING_RESPONSE_DISPLAY_NAMES,
    MeetingResponse,
    MeetingState,
    reminder_label,
)

#: Height a list row loses to ``QListWidget::item``'s padding and margin in
#: client/resources/{light,dark}.qss (8 px + 2 px, top and bottom): a widget
#: placed in a row only gets what is left, so a card's row must be this much
#: taller than the card, or its buttons are cut off. Keep in step with the QSS.
LIST_ITEM_CHROME = 2 * (8 + 2)


def meeting_when(meeting: dict) -> str:
    """When, in this computer's local time and zone: "Thu, Oct 30 · 3:00 PM – 4:00 PM CDT".

    The server sends UTC; each computer converts to its own zone, so people
    in different time zones each see the meeting's moment in their own time.
    """
    start, end = _local(meeting["starts_at"]), _local(meeting["ends_at"])
    start_zone, end_zone = zone_name(start), zone_name(end)
    if start_zone == end_zone:
        text = f"{start:%a, %b %d} · {_clock(start)} – {_clock(end)} {end_zone}"
    else:  # the clocks change during the meeting
        text = f"{start:%a, %b %d} · {_clock(start)} {start_zone} – {_clock(end)} {end_zone}"
    if end.date() != start.date():
        text += f" (ends {end:%a, %b %d})"
    return text


def meeting_day(meeting: dict) -> date:
    """The local calendar day the meeting starts on."""
    return _local(meeting["starts_at"]).date()


def meeting_status(meeting: dict) -> str:
    """One line on where things stand for you."""
    if meeting["state"] == MeetingState.CANCELLED:
        return "Cancelled"
    if meeting["has_ended"]:
        return "Ended"
    if meeting["is_host"]:
        return "You're hosting"
    response = meeting.get("my_response")
    if response:
        return f"Your reply: {MEETING_RESPONSE_DISPLAY_NAMES[MeetingResponse(response)]}"
    return "You haven't replied"


def meeting_counts(meeting: dict) -> str:
    counts = meeting["counts"]
    return (
        f"{counts['accepted']} accepted · {counts['tentative']} tentative · "
        f"{counts['declined']} declined · {counts['no_response']} no reply"
    )


def meeting_reminders(meeting: dict) -> str:
    """The host's reminders for everyone: "Reminders: 1 hour before, At start", or ""."""
    minutes = sorted(meeting.get("reminder_minutes") or [], reverse=True)
    return f"Reminders: {', '.join(reminder_label(m) for m in minutes)}" if minutes else ""


def meeting_summary(meeting: dict) -> str:
    """The whole card as one line: list item text, tooltips, screen readers."""
    where = f" ({meeting['team_name']})" if meeting.get("team_name") else ""
    return (
        f"Meeting: {meeting['title']}{where} · {meeting_when(meeting)} · {meeting_status(meeting)}"
    )


class MeetingCard(QFrame):
    """One meeting, with the actions you can take on it. Emits; doesn't act."""

    respond_clicked = Signal(int, str)
    join_clicked = Signal(int)
    edit_clicked = Signal(int)
    cancel_clicked = Signal(int)

    def __init__(self, meeting: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("meetingCard")
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.meeting = meeting

        self.title_label = ElidedLabel()
        self.title_label.setStyleSheet("font-weight: 600;")
        self.when_label = ElidedLabel()
        self.who_label = ElidedLabel()
        self.who_label.setProperty("muted", True)
        self.status_label = ElidedLabel()
        self.counts_label = ElidedLabel()
        self.counts_label.setProperty("muted", True)
        self.reminders_label = ElidedLabel()
        self.reminders_label.setProperty("muted", True)

        self.accept_button = QPushButton("Accept")
        self.tentative_button = QPushButton("Tentative")
        self.decline_button = QPushButton("Decline")
        self.join_button = QPushButton("Join")
        self.join_button.setProperty("primary", True)
        self.edit_button = QPushButton("Edit")
        self.cancel_button = QPushButton("Cancel meeting")

        buttons = QHBoxLayout()
        buttons.setContentsMargins(0, 0, 0, 0)
        for button in self._buttons():
            buttons.addWidget(button)
        buttons.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(2)
        layout.addWidget(self.title_label)
        layout.addWidget(self.when_label)
        layout.addWidget(self.who_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.counts_label)
        layout.addWidget(self.reminders_label)
        layout.addLayout(buttons)

        self.accept_button.clicked.connect(lambda: self._respond(MeetingResponse.ACCEPTED))
        self.tentative_button.clicked.connect(lambda: self._respond(MeetingResponse.TENTATIVE))
        self.decline_button.clicked.connect(lambda: self._respond(MeetingResponse.DECLINED))
        self.join_button.clicked.connect(lambda: self.join_clicked.emit(self.meeting["id"]))
        self.edit_button.clicked.connect(lambda: self.edit_clicked.emit(self.meeting["id"]))
        self.cancel_button.clicked.connect(lambda: self.cancel_clicked.emit(self.meeting["id"]))

        self.show_meeting(meeting)

    def show_meeting(self, meeting: dict) -> None:
        """Show (newer details of) the meeting."""
        self.meeting = meeting
        self.title_label.set_full_text(meeting["title"])
        self.when_label.set_full_text(meeting_when(meeting))
        team = f" · {meeting['team_name']}" if meeting.get("team_name") else ""
        self.who_label.set_full_text(f"Host: {meeting['host']['name']}{team}")
        self.status_label.set_full_text(meeting_status(meeting))
        self.counts_label.set_full_text(meeting_counts(meeting))
        reminders = meeting_reminders(meeting)
        self.reminders_label.set_full_text(reminders)
        self.reminders_label.setVisible(bool(reminders))
        self.setToolTip(meeting_summary(meeting))

        is_open = meeting["state"] == MeetingState.SCHEDULED and not meeting["has_ended"]
        can_reply = is_open and not meeting["is_host"]
        mine = meeting.get("my_response")
        for button, response in (
            (self.accept_button, MeetingResponse.ACCEPTED),
            (self.tentative_button, MeetingResponse.TENTATIVE),
            (self.decline_button, MeetingResponse.DECLINED),
        ):
            button.setVisible(can_reply)
            # Your current reply is shown as the status; its button is spent.
            button.setEnabled(mine != response)
        self.join_button.setVisible(is_open)
        # can_cancel: the host or an admin, who may also change it.
        self.edit_button.setVisible(is_open and meeting["can_cancel"])
        self.cancel_button.setVisible(is_open and meeting["can_cancel"])

    def row_size_hint(self) -> QSize:
        """The size a list row holding this card needs.

        Polished first: the app stylesheet makes buttons taller than Qt's
        defaults, and a size measured before it applies cut the buttons off.
        Plus the row's own padding (``LIST_ITEM_CHROME``).
        """
        self.ensurePolished()
        self.layout().activate()
        return self.sizeHint() + QSize(0, LIST_ITEM_CHROME)

    def _buttons(self) -> tuple[QPushButton, ...]:
        return (
            self.accept_button,
            self.tentative_button,
            self.decline_button,
            self.join_button,
            self.edit_button,
            self.cancel_button,
        )

    def set_busy(self, busy: bool) -> None:
        """Disable the buttons while a request is in flight."""
        for button in self._buttons():
            button.setEnabled(not busy)
        if not busy:
            self.show_meeting(self.meeting)

    def _respond(self, response: MeetingResponse) -> None:
        self.respond_clicked.emit(self.meeting["id"], response.value)


def add_card_item(list_widget: QListWidget, card: MeetingCard) -> QListWidgetItem:
    """Put a card in a list as one row.

    The row's own text is left empty (the card is drawn over it, and text
    would show through around the edges); the one-line summary goes in the
    row's accessible text and tooltip instead.
    """
    item = QListWidgetItem()
    summary = meeting_summary(card.meeting)
    item.setData(Qt.ItemDataRole.AccessibleTextRole, summary)
    item.setToolTip(summary)
    item.setSizeHint(card.row_size_hint())
    list_widget.addItem(item)
    list_widget.setItemWidget(item, card)
    return item


class MeetingsPanel(QGroupBox):
    """The Dashboard's Meetings list: a card per upcoming meeting.

    Re-emits every card's signals with the meeting id, so the page wires the
    actions up once rather than per card.
    """

    respond_clicked = Signal(int, str)
    join_clicked = Signal(int)
    edit_clicked = Signal(int)
    cancel_clicked = Signal(int)

    def __init__(self, title: str, empty_text: str, parent: QWidget | None = None) -> None:
        super().__init__(title, parent)
        self.list_widget = QListWidget()
        self.empty_label = QLabel(empty_text)
        self.empty_label.setProperty("muted", True)
        self.empty_label.setWordWrap(True)
        #: The cards shown, by meeting id.
        self.cards: dict[int, MeetingCard] = {}

        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout(self)
        layout.addLayout(self.header)
        layout.addWidget(self.empty_label)
        layout.addWidget(self.list_widget)
        self.set_meetings([])

    def set_meetings(self, meetings: list[dict]) -> None:
        """Show these meetings, in this order."""
        self.list_widget.clear()
        self.cards = {}
        for meeting in meetings:
            card = MeetingCard(meeting)
            card.respond_clicked.connect(self.respond_clicked)
            card.join_clicked.connect(self.join_clicked)
            card.edit_clicked.connect(self.edit_clicked)
            card.cancel_clicked.connect(self.cancel_clicked)
            add_card_item(self.list_widget, card)
            self.cards[meeting["id"]] = card
        self.empty_label.setVisible(not meetings)
        self.list_widget.setVisible(bool(meetings))

    def set_busy(self, busy: bool) -> None:
        for card in self.cards.values():
            card.set_busy(busy)
