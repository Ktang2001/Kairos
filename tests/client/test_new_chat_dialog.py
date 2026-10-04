from client.views.new_chat_dialog import NewChatDialog


class _FakeApiClient:
    user_id = 1

    def search_people(self, query: str) -> list[dict]:
        return [
            {"id": 1, "name": "Me", "email": "me@example.com"},
            {"id": 2, "name": "Bob Builder", "email": "bob@example.com"},
        ]


def test_search_excludes_self_and_accept_selects_person(qtbot) -> None:
    dialog = NewChatDialog(_FakeApiClient())
    qtbot.addWidget(dialog)

    dialog.search_input.setText("b")

    assert dialog.results_list.count() == 1
    assert "Bob Builder" in dialog.results_list.item(0).text()

    dialog.results_list.setCurrentRow(0)
    dialog._on_accept()

    assert dialog.result() == NewChatDialog.DialogCode.Accepted
    assert dialog.result_user_id == 2
    assert dialog.result_user_name == "Bob Builder"


def test_accept_without_selection_shows_error(qtbot) -> None:
    dialog = NewChatDialog(_FakeApiClient())
    qtbot.addWidget(dialog)

    dialog._on_accept()

    assert dialog.result() != NewChatDialog.DialogCode.Accepted
    assert "Select someone" in dialog.status_label.text()
