import httpx

from client.viewmodels.chat_viewmodel import ChatViewModel
from client.views.manage_members_dialog import ManageMembersDialog
from client.views.new_chat_dialog import NewChatDialog


class _FakeApiClient:
    def __init__(self, user_id: int, participants: list[dict]) -> None:
        self.user_id = user_id
        self._participants = participants
        self.removed: list[int] = []
        self.role_changes: list[tuple[int, str]] = []
        self.added: list[int] = []

    def get_conversation(self, conversation_id: int) -> dict:
        return {"id": conversation_id, "kind": "group", "participants": self._participants}

    def get_person(self, user_id: int) -> dict:
        names = {1: "Alice", 2: "Bob", 3: "Carol"}
        return {"id": user_id, "name": names.get(user_id, f"user-{user_id}")}

    def remove_participant(self, conversation_id: int, user_id: int) -> dict:
        self.removed.append(user_id)
        if user_id == 1 and len([p for p in self._participants if p["role"] == "admin"]) <= 1:
            raise httpx.HTTPStatusError("conflict", request=None, response=_Resp(409))
        self._participants = [p for p in self._participants if p["user_id"] != user_id]
        return {}

    def update_participant_role(self, conversation_id: int, user_id: int, role: str) -> dict:
        self.role_changes.append((user_id, role))
        for p in self._participants:
            if p["user_id"] == user_id:
                p["role"] = role
        return {}

    def add_participant(self, conversation_id: int, user_id: int, role: str = "member") -> dict:
        self.added.append(user_id)
        self._participants.append({"user_id": user_id, "role": role})
        return {}


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def json(self) -> dict:
        return {}


def test_non_admin_sees_no_action_buttons(qtbot):
    api = _FakeApiClient(
        user_id=2,
        participants=[{"user_id": 1, "role": "admin"}, {"user_id": 2, "role": "member"}],
    )
    vm = ChatViewModel(api, conversation_id=1)
    dialog = ManageMembersDialog(api, vm, conversation_id=1)
    qtbot.addWidget(dialog)

    assert dialog.members_list.count() == 2
    assert not dialog.add_member_button.isEnabled()
    # Every row widget for a non-admin viewer has just the name label, no buttons.
    for i in range(dialog.members_list.count()):
        row = dialog.members_list.itemWidget(dialog.members_list.item(i))
        from PySide6.QtWidgets import QPushButton

        assert row.findChildren(QPushButton) == []


def test_admin_can_promote_and_remove_others(qtbot):
    api = _FakeApiClient(
        user_id=1,
        participants=[
            {"user_id": 1, "role": "admin"},
            {"user_id": 2, "role": "member"},
            {"user_id": 3, "role": "member"},
        ],
    )
    vm = ChatViewModel(api, conversation_id=1)
    dialog = ManageMembersDialog(api, vm, conversation_id=1)
    qtbot.addWidget(dialog)

    assert dialog.add_member_button.isEnabled()

    dialog._on_toggle_role(2, "member")
    assert api.role_changes == [(2, "admin")]

    dialog._on_remove(3)
    assert api.removed == [3]
    assert dialog.members_list.count() == 2


def test_admin_cannot_target_themselves_in_row_buttons(qtbot):
    api = _FakeApiClient(
        user_id=1,
        participants=[{"user_id": 1, "role": "admin"}, {"user_id": 2, "role": "member"}],
    )
    vm = ChatViewModel(api, conversation_id=1)
    dialog = ManageMembersDialog(api, vm, conversation_id=1)
    qtbot.addWidget(dialog)

    from PySide6.QtWidgets import QPushButton

    self_row = dialog.members_list.itemWidget(dialog.members_list.item(0))
    other_row = dialog.members_list.itemWidget(dialog.members_list.item(1))

    assert self_row.findChildren(QPushButton) == []
    assert len(other_row.findChildren(QPushButton)) == 2


def test_last_admin_removal_shows_friendly_error(qtbot):
    api = _FakeApiClient(user_id=1, participants=[{"user_id": 1, "role": "admin"}])
    vm = ChatViewModel(api, conversation_id=1)
    dialog = ManageMembersDialog(api, vm, conversation_id=1)
    qtbot.addWidget(dialog)

    dialog._on_remove(1)

    assert "needs at least one admin" in dialog.status_label.text()


def test_add_member_flow(qtbot, monkeypatch):
    api = _FakeApiClient(user_id=1, participants=[{"user_id": 1, "role": "admin"}])
    vm = ChatViewModel(api, conversation_id=1)
    dialog = ManageMembersDialog(api, vm, conversation_id=1)
    qtbot.addWidget(dialog)

    def _fake_exec(self):
        self.result_user_id = 2
        self.result_user_name = "Bob"
        return NewChatDialog.DialogCode.Accepted

    monkeypatch.setattr(NewChatDialog, "exec", _fake_exec)

    dialog._on_add_member()

    assert api.added == [2]
    assert dialog.members_list.count() == 2
