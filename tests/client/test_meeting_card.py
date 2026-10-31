"""Tests for client/views/meeting_card.py: what a meeting card shows and offers."""

from datetime import UTC, datetime

import pytest
from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from client.views.meeting_card import (
    MeetingCard,
    MeetingsPanel,
    meeting_day,
    meeting_status,
    meeting_when,
)
from tests.client.meeting_data import make_meeting


def _card(qtbot: QtBot, **fields) -> MeetingCard:
    card = MeetingCard(make_meeting(**fields))
    qtbot.addWidget(card)
    card.show()
    return card


def _visible_buttons(card: MeetingCard) -> list[str]:
    return [
        button.text()
        for button in (
            card.accept_button,
            card.tentative_button,
            card.decline_button,
            card.join_button,
            card.cancel_button,
        )
        if button.isVisible()
    ]


# ---------------------------------------------------------------- buttons


def test_an_invitee_can_reply_and_join(qtbot: QtBot) -> None:
    card = _card(qtbot)

    assert _visible_buttons(card) == ["Accept", "Tentative", "Decline", "Join"]
    assert card.status_label.full_text == "You haven't replied"


def test_the_host_can_join_and_cancel_but_not_reply(qtbot: QtBot) -> None:
    card = _card(qtbot, is_host=True, can_cancel=True)

    assert _visible_buttons(card) == ["Join", "Cancel meeting"]
    assert card.status_label.full_text == "You're hosting"


def test_an_admin_viewer_can_also_cancel(qtbot: QtBot) -> None:
    card = _card(qtbot, can_cancel=True)

    assert "Cancel meeting" in _visible_buttons(card)


def test_your_current_reply_is_shown_and_its_button_spent(qtbot: QtBot) -> None:
    card = _card(qtbot, my_response="tentative")

    assert card.status_label.full_text == "Your reply: Tentative"
    assert not card.tentative_button.isEnabled()
    assert card.accept_button.isEnabled()
    assert card.decline_button.isEnabled()


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        ({"state": "cancelled", "can_cancel": True}, "Cancelled"),
        ({"has_ended": True, "is_host": True, "can_cancel": True}, "Ended"),
    ],
)
def test_a_cancelled_or_finished_meeting_has_no_buttons(
    qtbot: QtBot, fields: dict, status: str
) -> None:
    card = _card(qtbot, **fields)

    assert _visible_buttons(card) == []
    assert card.status_label.full_text == status


def test_buttons_emit_the_meeting_id(qtbot: QtBot) -> None:
    card = _card(qtbot, can_cancel=True)
    replies, joins, cancels = [], [], []
    card.respond_clicked.connect(lambda mid, response: replies.append((mid, response)))
    card.join_clicked.connect(joins.append)
    card.cancel_clicked.connect(cancels.append)

    card.accept_button.click()
    card.decline_button.click()
    card.join_button.click()
    card.cancel_button.click()

    assert replies == [(7, "accepted"), (7, "declined")]
    assert joins == [7]
    assert cancels == [7]


def test_busy_disables_then_restores_the_buttons(qtbot: QtBot) -> None:
    card = _card(qtbot, my_response="accepted")

    card.set_busy(True)
    assert not card.join_button.isEnabled()
    card.set_busy(False)
    assert card.join_button.isEnabled()
    assert not card.accept_button.isEnabled()  # still your current reply


def test_new_details_update_the_card(qtbot: QtBot) -> None:
    card = _card(qtbot)

    card.show_meeting(make_meeting(state="cancelled", title="Moved"))

    assert card.title_label.full_text == "Moved"
    assert _visible_buttons(card) == []


# ---------------------------------------------------------------- text


def test_the_title_is_plain_text(qtbot: QtBot) -> None:
    card = _card(qtbot, title='<b style="font-size:60px">HACKED</b>')

    assert card.title_label.textFormat() == Qt.TextFormat.PlainText
    assert card.title_label.full_text == '<b style="font-size:60px">HACKED</b>'


def test_counts_and_host_are_shown(qtbot: QtBot) -> None:
    card = _card(qtbot, counts={"accepted": 2, "tentative": 1, "declined": 0, "no_response": 3})

    assert card.counts_label.full_text == ("2 accepted · 1 tentative · 0 declined · 3 no reply")
    assert card.who_label.full_text == "Host: Lena · Alpha"


def test_times_are_shown_in_local_time() -> None:
    meeting = make_meeting(starts=datetime(2026, 11, 5, 15, 0, tzinfo=UTC))
    local_start = datetime(2026, 11, 5, 15, 0, tzinfo=UTC).astimezone()

    text = meeting_when(meeting)

    assert text.startswith(f"{local_start:%a, %b %d} · ")
    assert local_start.strftime("%I:%M %p").lstrip("0") in text
    assert meeting_day(meeting) == local_start.date()


def test_a_meeting_past_midnight_names_its_end_day() -> None:
    meeting = make_meeting(starts=datetime(2026, 11, 5, 23, 30).astimezone(), duration_minutes=60)

    assert "(ends Fri, Nov 06)" in meeting_when(meeting)


def test_status_for_a_reply() -> None:
    assert meeting_status(make_meeting(my_response="declined")) == "Your reply: Declined"


# ---------------------------------------------------------------- panel


def test_the_panel_shows_a_card_per_meeting_and_an_empty_state(qtbot: QtBot) -> None:
    panel = MeetingsPanel("Upcoming Meetings", "No upcoming meetings.")
    qtbot.addWidget(panel)

    assert not panel.empty_label.isHidden()

    panel.set_meetings([make_meeting(id=1), make_meeting(id=2, title="Retro")])

    assert panel.empty_label.isHidden()
    assert panel.list_widget.count() == 2
    assert set(panel.cards) == {1, 2}
    item = panel.list_widget.item(1)
    assert panel.list_widget.itemWidget(item) is panel.cards[2]
    assert "Retro" in item.data(Qt.ItemDataRole.AccessibleTextRole)
    # The card is drawn over the row; the row's own text stays empty.
    assert item.text() == ""


def test_the_panel_passes_card_clicks_on(qtbot: QtBot) -> None:
    panel = MeetingsPanel("Upcoming Meetings", "None.")
    qtbot.addWidget(panel)
    panel.set_meetings([make_meeting(id=4)])
    joins = []
    panel.join_clicked.connect(joins.append)

    panel.cards[4].join_button.click()

    assert joins == [4]


def test_the_host_or_an_admin_can_edit(qtbot: QtBot) -> None:
    host = _card(qtbot, is_host=True, can_cancel=True)
    invitee = _card(qtbot)
    edits = []
    host.edit_clicked.connect(edits.append)

    host.edit_button.click()

    assert host.edit_button.isVisible()
    assert not invitee.edit_button.isVisible()
    assert edits == [7]


def test_a_finished_meeting_cannot_be_edited(qtbot: QtBot) -> None:
    card = _card(qtbot, is_host=True, can_cancel=True, has_ended=True)

    assert not card.edit_button.isVisible()
