import pytest
from PySide6.QtCore import Qt

from client.views import chat_thread_panel
from client.views.chat_thread_panel import ChatThreadPanel
from tests.client.meeting_data import make_meeting


class _FakeApiClient:
    def __init__(self) -> None:
        self.user_id = 1
        self.base_url = "http://localhost:8000"
        self._messages_by_conversation: dict[int, list[dict]] = {
            1: [{"id": 1, "sender_user_id": 1, "body": "hello there", "attachments": []}]
        }
        self._conversation_kind: dict[int, str] = {1: "direct", 2: "group", 3: "group"}
        self._conversation_team: dict[int, int] = {3: 7}

    def get_conversation(self, conversation_id: int) -> dict:
        return {
            "id": conversation_id,
            "kind": self._conversation_kind.get(conversation_id, "direct"),
            "team_id": self._conversation_team.get(conversation_id),
        }

    def list_messages(self, conversation_id: int, after_id: int = 0, limit: int = 50) -> list[dict]:
        messages = self._messages_by_conversation.get(conversation_id, [])
        return [m for m in messages if m["id"] > after_id]

    def send_chat_message(self, conversation_id: int, body: str, client_token=None) -> dict:
        messages = self._messages_by_conversation.setdefault(conversation_id, [])
        message = {
            "id": len(messages) + 1,
            "sender_user_id": self.user_id,
            "body": body,
            "attachments": [],
        }
        messages.append(message)
        return message

    def get_person(self, user_id: int) -> dict:
        return {"id": user_id, "name": f"user-{user_id}"}


def test_shows_empty_state_before_any_selection(qtbot) -> None:
    panel = ChatThreadPanel(_FakeApiClient())
    qtbot.addWidget(panel)

    assert panel._pages.currentWidget() is panel._empty_page
    assert panel.view_model is None


def test_show_conversation_loads_history_and_switches_page(qtbot) -> None:
    panel = ChatThreadPanel(_FakeApiClient())
    qtbot.addWidget(panel)

    panel.show_conversation(1, title="Test Chat")

    assert panel._pages.currentWidget() is panel._thread_page
    assert panel.title_label.text() == "Test Chat"
    assert panel.message_list.count() == 1
    assert "hello there" in panel.message_list.item(0).text()


def test_sending_a_message_appends_it_and_clears_input(qtbot) -> None:
    panel = ChatThreadPanel(_FakeApiClient())
    qtbot.addWidget(panel)
    panel.show_conversation(1, title="Test Chat")

    panel.compose_input.setText("new message")
    panel._on_send()

    assert panel.compose_input.text() == ""
    assert panel.message_list.count() == 2
    assert "new message" in panel.message_list.item(1).text()


def test_switching_conversation_resets_cursor_and_history(qtbot) -> None:
    api = _FakeApiClient()
    panel = ChatThreadPanel(api)
    qtbot.addWidget(panel)

    panel.show_conversation(1, title="Chat One")
    assert panel.message_list.count() == 1

    panel.show_conversation(2, title="Chat Two")

    assert panel.title_label.text() == "Chat Two"
    assert panel.message_list.count() == 0  # fresh conversation, fresh cursor
    assert panel.view_model.conversation_id == 2


def test_same_timer_is_reused_across_conversation_switches(qtbot) -> None:
    panel = ChatThreadPanel(_FakeApiClient())
    qtbot.addWidget(panel)
    timer_before = panel._poll_timer

    panel.show_conversation(1, title="Chat One")
    panel.show_conversation(2, title="Chat Two")

    assert panel._poll_timer is timer_before  # one panel-owned timer, not one per conversation


def test_manage_members_button_only_shown_for_group_conversations(qtbot) -> None:
    panel = ChatThreadPanel(_FakeApiClient())
    qtbot.addWidget(panel)
    panel.show()  # isVisible() only reflects real state once the hierarchy is shown

    panel.show_conversation(1, title="Direct Chat")
    assert not panel.manage_members_button.isVisible()

    panel.show_conversation(2, title="Group Chat")
    assert panel.manage_members_button.isVisible()


def test_manage_members_button_hidden_for_a_team_chat(qtbot) -> None:
    panel = ChatThreadPanel(_FakeApiClient())
    qtbot.addWidget(panel)
    panel.show()

    panel.show_conversation(3, title="Alpha")

    assert not panel.manage_members_button.isVisible()


# ------------------------------------------------------------------ meetings


class _MeetingApi(_FakeApiClient):
    """A chat (id 3) whose one message announces meeting 7."""

    def __init__(self) -> None:
        super().__init__()
        self._messages_by_conversation[3] = [
            {
                "id": 1,
                "sender_user_id": 2,
                "body": "Scheduled a meeting: Stand-up",
                "attachments": [],
                "meeting_id": 7,
            }
        ]
        self.meetings = [make_meeting(id=7, conversation_id=3)]
        self.meeting_requests = 0

    def list_chat_meetings(self, conversation_id: int) -> list[dict]:
        self.meeting_requests += 1
        return [m for m in self.meetings if m["conversation_id"] == conversation_id]


def test_a_meeting_announcement_becomes_its_card(qtbot) -> None:
    api = _MeetingApi()
    panel = ChatThreadPanel(api)
    qtbot.addWidget(panel)

    panel.show_conversation(3, title="Alpha")
    # Until the meeting's details arrive the row shows the announcement.
    assert "Scheduled a meeting: Stand-up" in panel.message_list.item(0).text()
    qtbot.waitUntil(lambda: 7 in panel._meeting_cards, timeout=5000)

    item = panel.message_list.item(0)
    card = panel._meeting_cards[7]
    assert panel.message_list.itemWidget(item) is card
    assert item.text() == ""
    assert "Stand-up" in item.data(Qt.ItemDataRole.AccessibleTextRole)


def test_each_poll_brings_the_cards_up_to_date(qtbot) -> None:
    api = _MeetingApi()
    panel = ChatThreadPanel(api)
    qtbot.addWidget(panel)
    panel.show_conversation(3, title="Alpha")
    qtbot.waitUntil(lambda: 7 in panel._meeting_cards, timeout=5000)

    api.meetings = [make_meeting(id=7, conversation_id=3, state="cancelled")]
    panel._refresh()

    qtbot.waitUntil(
        lambda: panel._meeting_cards[7].status_label.full_text == "Cancelled", timeout=5000
    )


def test_a_chat_without_meetings_never_asks_for_them(qtbot) -> None:
    api = _MeetingApi()
    panel = ChatThreadPanel(api)
    qtbot.addWidget(panel)

    panel.show_conversation(1, title="Direct")
    panel._refresh()

    assert api.meeting_requests == 0


def test_cards_for_a_chat_you_left_are_ignored(qtbot) -> None:
    api = _MeetingApi()
    panel = ChatThreadPanel(api)
    qtbot.addWidget(panel)
    panel.show_conversation(3, title="Alpha")
    panel.show_conversation(1, title="Direct")

    panel._show_meetings(3, api.meetings)

    assert panel._meeting_cards == {}


class _AcceptedDialog:
    """Stands in for NewMeetingDialog: the user filled it in and pressed OK."""

    class DialogCode:
        Accepted = 1

    def __init__(self, *_args, **_kwargs) -> None:
        self.result_title = "Quick call"
        self.result_starts_at = None
        self.result_duration_minutes = 30
        self.result_client_token = "tok"
        self.result_reminder_minutes = []

    def exec(self) -> int:
        return 1


def test_the_meet_button_starts_a_meeting_in_this_chat(
    qtbot, monkeypatch: pytest.MonkeyPatch
) -> None:
    panel = ChatThreadPanel(_MeetingApi())
    qtbot.addWidget(panel)
    panel.show_conversation(3, title="Alpha")
    requests = []
    monkeypatch.setattr(chat_thread_panel, "NewMeetingDialog", _AcceptedDialog)
    monkeypatch.setattr(
        panel.meetings, "create_in_chat", lambda cid, **fields: requests.append((cid, fields))
    )

    panel.meet_button.click()

    assert requests == [
        (
            3,
            {
                "title": "Quick call",
                "starts_at": None,
                "duration_minutes": 30,
                "client_token": "tok",
                "reminder_minutes": [],
            },
        )
    ]


def test_cancelling_from_a_card_asks_first(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    panel = ChatThreadPanel(_MeetingApi())
    qtbot.addWidget(panel)
    panel.show_conversation(3, title="Alpha")
    qtbot.waitUntil(lambda: 7 in panel._meeting_cards, timeout=5000)
    cancelled = []
    monkeypatch.setattr(panel.meetings, "cancel", cancelled.append)

    panel.confirm = lambda _title, _question: False
    panel._confirm_cancel(7)
    assert cancelled == []

    panel.confirm = lambda _title, question: "Stand-up" in question
    panel._confirm_cancel(7)
    assert cancelled == [7]
