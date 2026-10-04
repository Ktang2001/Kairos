from client.api_client import ApiClient
from client.views.chat_page import ChatPage
from client.views.new_chat_dialog import NewChatDialog
from client.views.new_group_dialog import NewGroupDialog


def test_loads_conversations_on_init(qtbot, monkeypatch) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
    monkeypatch.setattr(
        ApiClient,
        "list_conversations",
        lambda self: [
            {
                "id": 1,
                "kind": "direct",
                "name": None,
                "created_at": "2026-10-01T00:00:00",
                "participants": [
                    {"user_id": 1, "role": "member"},
                    {"user_id": 2, "role": "member"},
                ],
            }
        ],
    )
    monkeypatch.setattr(ApiClient, "get_person", lambda self, uid: {"id": uid, "name": "Bob"})

    page = ChatPage(api)
    qtbot.addWidget(page)

    assert page.conversations_list.count() == 1
    assert "Bob" in page.conversations_list.item(0).text()


def test_empty_state_message(qtbot, monkeypatch) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])

    page = ChatPage(api)
    qtbot.addWidget(page)

    assert page.conversations_list.count() == 1
    assert "No conversations" in page.conversations_list.item(0).text()


def test_selecting_a_conversation_shows_it_inline_no_popup(qtbot, monkeypatch) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
    monkeypatch.setattr(
        ApiClient,
        "list_conversations",
        lambda self: [
            {
                "id": 1,
                "kind": "group",
                "name": "Project Team",
                "created_at": "2026-10-01T00:00:00",
                "participants": [{"user_id": 1, "role": "admin"}],
            }
        ],
    )
    monkeypatch.setattr(ApiClient, "list_messages", lambda self, cid, after_id=0, limit=50: [])

    page = ChatPage(api)
    qtbot.addWidget(page)

    page.conversations_list.setCurrentRow(0)

    assert page.thread_panel.view_model is not None
    assert page.thread_panel.view_model.conversation_id == 1
    assert "Project Team" in page.thread_panel.title_label.text()


def test_new_chat_flow_selects_the_new_conversation(qtbot, monkeypatch) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(
        ApiClient, "start_direct_conversation", lambda self, other_user_id: {"id": 5}
    )
    monkeypatch.setattr(ApiClient, "list_messages", lambda self, cid, after_id=0, limit=50: [])

    def _fake_exec(self):
        self.result_user_id = 2
        self.result_user_name = "Bob"
        return NewChatDialog.DialogCode.Accepted

    monkeypatch.setattr(NewChatDialog, "exec", _fake_exec)

    page = ChatPage(api)
    qtbot.addWidget(page)

    page._on_new_chat_clicked()

    assert page.thread_panel.view_model is not None
    assert page.thread_panel.view_model.conversation_id == 5
    assert page.thread_panel.title_label.text() == "Chat with Bob"


def test_new_group_flow_selects_the_new_conversation(qtbot, monkeypatch) -> None:
    api = ApiClient(base_url="http://localhost:8000", user_id=1)
    monkeypatch.setattr(ApiClient, "list_conversations", lambda self: [])
    monkeypatch.setattr(
        ApiClient,
        "create_group_conversation",
        lambda self, name, member_user_ids: {"id": 9, "name": name},
    )
    monkeypatch.setattr(ApiClient, "list_messages", lambda self, cid, after_id=0, limit=50: [])

    def _fake_exec(self):
        self.result_name = "Project Team"
        self.result_member_ids = [2, 3]
        return NewGroupDialog.DialogCode.Accepted

    monkeypatch.setattr(NewGroupDialog, "exec", _fake_exec)

    page = ChatPage(api)
    qtbot.addWidget(page)

    page._on_new_group_clicked()

    assert page.thread_panel.view_model is not None
    assert page.thread_panel.view_model.conversation_id == 9
    assert page.thread_panel.title_label.text() == "Project Team"
