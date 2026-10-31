"""Tests for meeting reminders (client/viewmodels/meeting_reminders.py), the
reminder pop-up (client/views/reminder_popup.py) and time-zone names on
meeting times (client/views/meeting_card.py).
"""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings, Qt
from pytestqt.qtbot import QtBot

from client.viewmodels.meeting_preferences import MeetingPreferences
from client.viewmodels.meeting_reminders import (
    MeetingReminders,
    due_reminders,
    reminder_message,
)
from client.views.meeting_card import MeetingCard, meeting_when, zone_name
from client.views.meeting_dialog import NewMeetingDialog
from client.views.reminder_popup import ReminderNotifier, ReminderPopup
from tests.client.meeting_data import make_meeting

START = datetime(2026, 11, 5, 15, 0, tzinfo=UTC)
SERVER = "https://kairos.test:8000"


def _due(meetings, now, default=15, fired=()):
    return due_reminders(
        meetings, now=now, default_minutes=default, fired=set(fired), server=SERVER
    )


def _ids(meetings: list[dict]) -> list[int]:
    return [m["id"] for m in meetings]


# ------------------------------------------------------------ when it fires


def test_nothing_is_due_before_your_default_time() -> None:
    shown, used = _due([make_meeting(starts=START)], START - timedelta(minutes=16))

    assert shown == [] and used == []


def test_your_default_reminder_fires_once() -> None:
    meeting = make_meeting(starts=START)
    now = START - timedelta(minutes=15)

    shown, used = _due([meeting], now)
    assert _ids(shown) == [7]

    again, _ = _due([meeting], now + timedelta(minutes=1), fired=used)
    assert again == []


def test_the_hosts_reminders_come_on_top_of_yours() -> None:
    meeting = make_meeting(starts=START, reminder_minutes=[60])

    shown, used = _due([meeting], START - timedelta(minutes=60))
    assert _ids(shown) == [7]

    shown, _ = _due([meeting], START - timedelta(minutes=15), fired=used)
    assert _ids(shown) == [7]  # your own 15-minute default, separately


def test_a_host_reminder_at_the_same_time_as_yours_goes_off_once() -> None:
    meeting = make_meeting(starts=START, reminder_minutes=[15])

    shown, used = _due([meeting], START - timedelta(minutes=15))

    assert _ids(shown) == [7]
    assert len(used) == 1


def test_several_overdue_reminders_show_as_one() -> None:
    # Kairos opened 10 minutes before: the 60- and 15-minute ones are both due.
    meeting = make_meeting(starts=START, reminder_minutes=[60, 30])

    shown, used = _due([meeting], START - timedelta(minutes=10))

    assert _ids(shown) == [7]
    assert len(used) == 3
    assert _due([meeting], START - timedelta(minutes=9), fired=used)[0] == []


def test_an_at_start_reminder_fires_at_the_start() -> None:
    meeting = make_meeting(starts=START, reminder_minutes=[0])
    _, used = _due([meeting], START - timedelta(minutes=15))

    assert _due([meeting], START - timedelta(seconds=1), fired=used)[0] == []
    assert _ids(_due([meeting], START, fired=used)[0]) == [7]


def test_with_your_default_off_only_the_hosts_reminders_fire() -> None:
    assert _due([make_meeting(starts=START)], START, default=None)[0] == []

    meeting = make_meeting(starts=START, reminder_minutes=[5])
    assert _ids(_due([meeting], START - timedelta(minutes=5), default=None)[0]) == [7]


@pytest.mark.parametrize(
    "fields",
    [
        {"my_response": "declined"},
        {"state": "cancelled"},
        {"has_ended": True},
    ],
)
def test_no_reminder_for_a_declined_cancelled_or_finished_meeting(fields: dict) -> None:
    assert _due([make_meeting(starts=START, **fields)], START - timedelta(minutes=5))[0] == []


@pytest.mark.parametrize("response", [None, "accepted", "tentative"])
def test_everyone_but_decliners_is_reminded(response) -> None:
    meeting = make_meeting(starts=START, my_response=response)

    assert _ids(_due([meeting], START - timedelta(minutes=5))[0]) == [7]


def test_no_reminder_once_the_meeting_is_over() -> None:
    meeting = make_meeting(starts=START, duration_minutes=30)

    assert _due([meeting], START + timedelta(minutes=30))[0] == []


def test_the_host_of_an_instant_meeting_isnt_reminded_but_invitees_are() -> None:
    instant = {"created_at": START.isoformat()}

    host_view = make_meeting(starts=START, is_host=True, **instant)
    shown, used = _due([host_view], START + timedelta(seconds=10))
    assert shown == []
    assert used  # and it won't come up later either

    invitee_view = make_meeting(starts=START, **instant)
    assert _ids(_due([invitee_view], START + timedelta(seconds=10))[0]) == [7]


def test_the_host_of_a_scheduled_meeting_is_reminded() -> None:
    meeting = make_meeting(starts=START, is_host=True)

    assert _ids(_due([meeting], START - timedelta(minutes=15))[0]) == [7]


def test_time_zones_dont_matter_only_the_moment() -> None:
    # Scheduled by someone at UTC+9 for 00:00 their time = 15:00 UTC.
    tokyo = timezone(timedelta(hours=9))
    meeting = make_meeting(starts=START.astimezone(tokyo))
    chicago_now = (START - timedelta(minutes=15)).astimezone(timezone(timedelta(hours=-5)))

    assert _ids(_due([meeting], chicago_now)[0]) == [7]
    assert _due([meeting], chicago_now - timedelta(minutes=1))[0] == []


def test_reminders_on_another_server_are_kept_apart() -> None:
    meeting = make_meeting(starts=START)
    _, used = _due([meeting], START - timedelta(minutes=15))

    shown, _ = due_reminders(
        [meeting],
        now=START - timedelta(minutes=15),
        default_minutes=15,
        fired=set(used),
        server="https://other:8000",
    )

    assert _ids(shown) == [7]


@pytest.mark.parametrize(
    ("offset", "message"),
    [
        (timedelta(minutes=15), "Starts in 15 minutes"),
        (timedelta(minutes=1), "Starts in 1 minute"),
        (timedelta(minutes=65), "Starts in 1 hour 5 minutes"),
        (timedelta(hours=2), "Starts in 2 hours"),
        (timedelta(seconds=20), "Starting now"),
        (timedelta(seconds=-20), "Starting now"),
        (timedelta(minutes=-3), "Started 3 minutes ago"),
        (timedelta(minutes=14, seconds=30), "Starts in 15 minutes"),
    ],
)
def test_the_message_says_how_long_until_the_start(offset: timedelta, message: str) -> None:
    assert reminder_message(make_meeting(starts=START), START - offset) == message


# ------------------------------------------------------ the scheduler object


class _FakeClient:
    base_url = SERVER

    def __init__(self, meetings: list[dict]) -> None:
        self.meetings = meetings
        self.requests = 0

    def list_upcoming_meetings(self) -> list[dict]:
        self.requests += 1
        return self.meetings


@pytest.fixture
def preferences(tmp_path: Path) -> MeetingPreferences:
    return MeetingPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))


def _scheduler(client, preferences, now) -> tuple[MeetingReminders, list]:
    reminders = MeetingReminders(client, preferences, clock=lambda: now)
    shown: list = []
    reminders.reminder_due.connect(lambda meeting, message: shown.append((meeting["id"], message)))
    return reminders, shown


def test_the_scheduler_fetches_and_reminds_once(
    qtbot: QtBot, preferences: MeetingPreferences
) -> None:
    client = _FakeClient([make_meeting(starts=START)])
    reminders, shown = _scheduler(client, preferences, START - timedelta(minutes=15))

    reminders.start()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)
    reminders.check()
    reminders.stop()

    assert shown == [(7, "Starts in 15 minutes")]


def test_a_shown_reminder_isnt_repeated_after_a_restart(
    qtbot: QtBot, preferences: MeetingPreferences, tmp_path: Path
) -> None:
    client = _FakeClient([make_meeting(starts=START)])
    first, shown = _scheduler(client, preferences, START - timedelta(minutes=15))
    first.refresh()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    # A new window (Kairos restarted), same settings file.
    reopened = MeetingPreferences(
        QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    )
    second, shown_again = _scheduler(client, reopened, START - timedelta(minutes=14))
    second.refresh()
    qtbot.waitUntil(lambda: bool(second.meetings), timeout=5000)

    assert shown_again == []


def test_the_profile_default_is_used(qtbot: QtBot, preferences: MeetingPreferences) -> None:
    preferences.reminder_minutes = 60
    client = _FakeClient([make_meeting(starts=START)])
    reminders, shown = _scheduler(client, preferences, START - timedelta(minutes=60))

    reminders.refresh()
    qtbot.waitUntil(lambda: bool(shown), timeout=5000)

    assert shown == [(7, "Starts in 1 hour")]


# ---------------------------------------------------------------- preferences


def test_the_default_reminder_is_15_minutes(preferences: MeetingPreferences) -> None:
    assert preferences.reminder_minutes == 15


def test_the_default_reminder_can_be_off(preferences: MeetingPreferences) -> None:
    preferences.reminder_minutes = None

    assert preferences.reminder_minutes is None


def test_an_unexpected_stored_reminder_reads_as_the_default(tmp_path: Path) -> None:
    settings = QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat)
    settings.setValue("meetings/reminder_minutes", "banana")

    assert MeetingPreferences(settings).reminder_minutes == 15


def test_only_offered_reminder_times_can_be_saved(preferences: MeetingPreferences) -> None:
    with pytest.raises(ValueError):
        preferences.reminder_minutes = 7


def test_only_the_newest_shown_reminders_are_remembered(
    preferences: MeetingPreferences,
) -> None:
    preferences.remember_fired([f"k{i}" for i in range(400)])

    remembered = preferences.fired_reminders()
    assert len(remembered) == 300
    assert remembered[-1] == "k399"


# ---------------------------------------------------------------- pop-up


def test_the_popup_shows_the_meeting_and_joins(qtbot: QtBot) -> None:
    popup = ReminderPopup(make_meeting(title="<b>Stand-up</b>"), "Starts in 15 minutes")
    qtbot.addWidget(popup)
    joins = []
    popup.join_clicked.connect(joins.append)

    assert popup.title_label.textFormat() == Qt.TextFormat.PlainText
    assert popup.title_label.full_text == "<b>Stand-up</b>"
    assert popup.message_label.text() == "Starts in 15 minutes"

    popup.join_button.click()
    assert joins == [7]


def test_a_second_reminder_updates_the_open_popup(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QWidget

    window = QWidget()
    qtbot.addWidget(window)
    notifier = ReminderNotifier(window)

    notifier.notify(make_meeting(), "Starts in 15 minutes")
    notifier.notify(make_meeting(), "Starting now")

    assert list(notifier.popups) == [7]
    assert notifier.popups[7].message_label.text() == "Starting now"
    notifier.close_all()


# ---------------------------------------------------------------- dialog


def test_reminders_for_everyone_are_only_for_a_scheduled_meeting(qtbot: QtBot) -> None:
    dialog = NewMeetingDialog()
    qtbot.addWidget(dialog)
    dialog.title_input.setText("Planning")
    dialog.reminder_boxes[15].setChecked(True)

    assert not dialog.reminders_group.isEnabled()
    dialog._on_accept()
    assert dialog.result_reminder_minutes == []


def test_chosen_reminders_are_returned_sorted(qtbot: QtBot) -> None:
    dialog = NewMeetingDialog()
    qtbot.addWidget(dialog)
    dialog.title_input.setText("Planning")
    dialog.schedule_option.setChecked(True)
    dialog.when_input.setDateTime(dialog.when_input.dateTime().addDays(2))
    for minutes in (60, 0, 15):
        dialog.reminder_boxes[minutes].setChecked(True)

    dialog._on_accept()

    assert dialog.reminders_group.isEnabled()
    assert dialog.result_reminder_minutes == [0, 15, 60]


def test_the_dialog_names_your_time_zone(qtbot: QtBot) -> None:
    dialog = NewMeetingDialog()
    qtbot.addWidget(dialog)

    assert dialog.zone_label.text() == (f"Your time zone: {zone_name(datetime.now().astimezone())}")


# ---------------------------------------------------------------- time zones


@pytest.mark.parametrize(
    ("zone", "name"),
    [
        (timezone(timedelta(hours=-5), "CDT"), "CDT"),
        (timezone(timedelta(hours=1), "BST"), "BST"),
        # Windows: long names only. Common ones are shortened, others fall back.
        (timezone(timedelta(hours=-5), "Central Daylight Time"), "CDT"),
        (timezone(timedelta(hours=1), "GMT Daylight Time"), "BST"),
        (timezone(timedelta(hours=3), "Arab Standard Time"), "UTC+3"),
        # Zones with no letters at all.
        (timezone(timedelta(hours=5, minutes=30)), "UTC+5:30"),
        (timezone(timedelta(hours=4), "+04"), "UTC+4"),
        (timezone(timedelta(hours=-3, minutes=-30), "-0330"), "UTC-3:30"),
        (UTC, "UTC"),
    ],
)
def test_zone_names(zone: timezone, name: str) -> None:
    assert zone_name(datetime(2026, 11, 5, 12, 0, tzinfo=zone)) == name


def test_meeting_times_end_with_your_zone() -> None:
    meeting = make_meeting(starts=START)
    local_end = (START + timedelta(hours=1)).astimezone()

    assert meeting_when(meeting).endswith(zone_name(local_end))


def test_the_card_lists_the_hosts_reminders(qtbot: QtBot) -> None:
    card = MeetingCard(make_meeting(reminder_minutes=[0, 60, 1440]))
    qtbot.addWidget(card)

    assert card.reminders_label.full_text == ("Reminders: 1 day before, 1 hour before, At start")
    assert not card.reminders_label.isHidden()

    card.show_meeting(make_meeting())
    assert card.reminders_label.isHidden()


def test_without_a_tray_the_notice_goes_through_notify_send(qtbot: QtBot) -> None:
    from PySide6.QtWidgets import QWidget

    window = QWidget()
    qtbot.addWidget(window)
    notifier = ReminderNotifier(window)
    notifier._tray = None  # as on GNOME without a tray extension
    notifier.notify_send = "/usr/bin/notify-send"
    sent = []
    notifier.run_command = lambda program, args: sent.append((program, args)) or True

    notifier.notify(make_meeting(title="Stand-up; rm -rf ~"), "Starts in 15 minutes")

    [(program, args)] = sent
    assert program == "/usr/bin/notify-send"
    # Passed as separate arguments after "--": nothing in a title is run or
    # read as an option.
    assert args[args.index("--") + 1] == "Stand-up; rm -rf ~"
    assert args[-1].startswith("Starts in 15 minutes · ")
    notifier.close_all()
