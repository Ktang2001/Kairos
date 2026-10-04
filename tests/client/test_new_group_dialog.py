from PySide6.QtCore import Qt

from client.views.new_group_dialog import NewGroupDialog


class _FakeApiClient:
    user_id = 1

    def __init__(self) -> None:
        self.people = [
            {"id": 1, "name": "Me", "email": "me@example.com"},
            {"id": 2, "name": "Bob Builder", "email": "bob@example.com"},
            {"id": 3, "name": "Carol Coder", "email": "carol@example.com"},
        ]

    def search_people(self, query: str) -> list[dict]:
        query = query.lower()
        return [p for p in self.people if query in p["name"].lower()]


def test_checking_people_updates_selected_label(qtbot):
    dialog = NewGroupDialog(_FakeApiClient())
    qtbot.addWidget(dialog)

    dialog.search_input.setText("o")  # matches Bob and Carol
    assert dialog.results_list.count() == 2

    dialog.results_list.item(0).setCheckState(Qt.CheckState.Checked)

    assert "Bob Builder" in dialog.selected_label.text()


def test_selection_persists_across_new_searches(qtbot):
    dialog = NewGroupDialog(_FakeApiClient())
    qtbot.addWidget(dialog)

    dialog.search_input.setText("bob")
    dialog.results_list.item(0).setCheckState(Qt.CheckState.Checked)

    dialog.search_input.setText("carol")
    dialog.results_list.item(0).setCheckState(Qt.CheckState.Checked)

    assert set(dialog._selected.values()) == {"Bob Builder", "Carol Coder"}


def test_accept_requires_name_and_at_least_one_member(qtbot):
    dialog = NewGroupDialog(_FakeApiClient())
    qtbot.addWidget(dialog)

    dialog._on_accept()
    assert dialog.result() != NewGroupDialog.DialogCode.Accepted
    assert "name is required" in dialog.status_label.text()

    dialog.name_input.setText("Project Team")
    dialog._on_accept()
    assert dialog.result() != NewGroupDialog.DialogCode.Accepted
    assert "at least one" in dialog.status_label.text()

    dialog.search_input.setText("bob")
    dialog.results_list.item(0).setCheckState(Qt.CheckState.Checked)
    dialog._on_accept()

    assert dialog.result() == NewGroupDialog.DialogCode.Accepted
    assert dialog.result_name == "Project Team"
    assert dialog.result_member_ids == [2]
