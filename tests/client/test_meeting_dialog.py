"""Tests for client/views/meeting_dialog.py: asking for a meeting's details."""

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QDateTime, QTime
from pytestqt.qtbot import QtBot

from client.views.meeting_dialog import NewMeetingDialog, _next_half_hour
from shared.meetings import DEFAULT_DURATION_MINUTES, MAX_DURATION_MINUTES


def _dialog(qtbot: QtBot, **kwargs) -> NewMeetingDialog:
    dialog = NewMeetingDialog(**kwargs)
    qtbot.addWidget(dialog)
    return dialog


def _set_when(dialog: NewMeetingDialog, moment: datetime) -> None:
    dialog.when_input.setDateTime(
        QDateTime(QDate(moment.year, moment.month, moment.day), QTime(moment.hour, moment.minute))
    )


def test_start_now_by_default(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)
    dialog.title_input.setText("  Quick sync  ")

    dialog._on_accept()

    assert dialog.result() == NewMeetingDialog.DialogCode.Accepted
    assert dialog.result_title == "Quick sync"
    assert dialog.result_starts_at is None
    assert dialog.result_duration_minutes == DEFAULT_DURATION_MINUTES
    assert dialog.result_team_id is None
    assert len(dialog.result_client_token) == 32


def test_the_time_picker_is_only_used_when_scheduling(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)

    assert not dialog.when_input.isEnabled()
    dialog.schedule_option.setChecked(True)
    assert dialog.when_input.isEnabled()


def test_a_scheduled_time_is_sent_with_this_computers_offset(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)
    dialog.title_input.setText("Planning")
    dialog.schedule_option.setChecked(True)
    when = (datetime.now() + timedelta(days=3)).replace(hour=14, minute=30, second=0, microsecond=0)
    _set_when(dialog, when)
    dialog.duration_input.setValue(45)

    dialog._on_accept()

    assert dialog.result_starts_at is not None
    assert dialog.result_starts_at.tzinfo is not None
    assert dialog.result_starts_at == when.astimezone()
    assert dialog.result_duration_minutes == 45


def test_a_past_time_is_refused(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)
    dialog.title_input.setText("Too late")
    dialog.schedule_option.setChecked(True)
    _set_when(dialog, datetime.now() - timedelta(hours=2))

    dialog._on_accept()

    assert dialog.result() != NewMeetingDialog.DialogCode.Accepted
    assert "passed" in dialog.error_label.text()


def test_a_blank_or_invisible_title_is_refused(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)
    dialog.title_input.setText(" \u200b ")

    dialog._on_accept()

    assert dialog.result() != NewMeetingDialog.DialogCode.Accepted
    assert "title" in dialog.error_label.text()


def test_the_duration_is_capped(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot)

    dialog.duration_input.setValue(10_000)

    assert dialog.duration_input.value() == MAX_DURATION_MINUTES


def test_the_team_picker_preselects_and_returns_the_team(qtbot: QtBot) -> None:
    teams = [{"id": 1, "name": "Alpha"}, {"id": 2, "name": "Beta"}]
    dialog = _dialog(qtbot, teams=teams, team_id=2)
    dialog.title_input.setText("Retro")

    dialog._on_accept()

    assert dialog.result_team_id == 2


def test_with_an_empty_team_list_nothing_is_accepted(qtbot: QtBot) -> None:
    dialog = _dialog(qtbot, teams=[])
    dialog.title_input.setText("Retro")

    dialog._on_accept()

    assert dialog.result() != NewMeetingDialog.DialogCode.Accepted


def test_each_dialog_gets_its_own_request_id(qtbot: QtBot) -> None:
    assert _dialog(qtbot).result_client_token != _dialog(qtbot).result_client_token


def test_the_default_start_is_the_next_half_hour() -> None:
    assert _next_half_hour(datetime(2026, 11, 5, 14, 7)) == datetime(2026, 11, 5, 14, 30)
    assert _next_half_hour(datetime(2026, 11, 5, 14, 30)) == datetime(2026, 11, 5, 15, 0)
    assert _next_half_hour(datetime(2026, 11, 5, 23, 45)) == datetime(2026, 11, 6, 0, 0)


# ---------------------------------------------------------------- editing


def _editing(qtbot: QtBot, **fields) -> NewMeetingDialog:
    from tests.client.meeting_data import make_meeting

    return _dialog(qtbot, meeting=make_meeting(**fields))


def test_editing_fills_in_the_meeting_in_local_time(qtbot: QtBot) -> None:
    from datetime import UTC

    starts = datetime(2027, 3, 1, 15, 0, tzinfo=UTC)
    dialog = _editing(
        qtbot, starts=starts, title="Retro", duration_minutes=45, reminder_minutes=[0, 60]
    )

    assert dialog.windowTitle() == "Edit meeting"
    assert dialog.title_input.text() == "Retro"
    assert dialog.now_option.isHidden()
    assert dialog.when_input.dateTime().toPython() == starts.astimezone().replace(tzinfo=None)
    assert dialog.duration_input.value() == 45
    assert [m for m, box in dialog.reminder_boxes.items() if box.isChecked()] == [0, 60]

    dialog._on_accept()
    assert dialog.result_starts_at == starts
    assert dialog.result_reminder_minutes == [0, 60]


def test_a_meeting_under_way_can_be_renamed_without_moving_it(qtbot: QtBot) -> None:
    from datetime import UTC

    started = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(minutes=20)
    dialog = _editing(qtbot, starts=started)
    dialog.title_input.setText("Stand-up (running late)")

    dialog._on_accept()

    assert dialog.result() == NewMeetingDialog.DialogCode.Accepted
    assert dialog.result_title == "Stand-up (running late)"


def test_editing_cannot_move_a_meeting_into_the_past(qtbot: QtBot) -> None:
    dialog = _editing(qtbot)
    _set_when(dialog, datetime.now() - timedelta(hours=3))

    dialog._on_accept()

    assert dialog.result() != NewMeetingDialog.DialogCode.Accepted
