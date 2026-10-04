from client.views.chat_thread_panel import ChatThreadPanel


class _FakeApiClient:
    def __init__(self) -> None:
        self.user_id = 1
        self.base_url = "http://localhost:8000"
        self._messages_by_conversation: dict[int, list[dict]] = {
            1: [{"id": 1, "sender_user_id": 1, "body": "hello there", "attachments": []}]
        }
        self._conversation_kind: dict[int, str] = {1: "direct", 2: "group"}

    def get_conversation(self, conversation_id: int) -> dict:
        return {
            "id": conversation_id,
            "kind": self._conversation_kind.get(conversation_id, "direct"),
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
