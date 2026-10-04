import httpx

from client.views.add_server_dialog import AddServerDialog


class _FakeResponse:
    def __init__(self, json_body: dict) -> None:
        self._json_body = json_body

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._json_body


def test_accept_fetches_and_stores_display_name(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx, "get", lambda url, timeout=5: _FakeResponse({"display_name": "Kairos Server"})
    )

    dialog = AddServerDialog()
    qtbot.addWidget(dialog)
    dialog.host_input.setText("192.168.1.20")
    dialog.port_input.setValue(8001)
    dialog.nickname_input.setText("Office PC")

    dialog._on_accept()

    assert dialog.result() == AddServerDialog.DialogCode.Accepted
    assert dialog.result_host == "192.168.1.20"
    assert dialog.result_port == 8001
    assert dialog.result_display_name == "Kairos Server"
    assert dialog.result_nickname == "Office PC"


def test_accept_shows_error_when_unreachable(qtbot, monkeypatch) -> None:
    def _raise(url, timeout=5):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx, "get", _raise)

    dialog = AddServerDialog()
    qtbot.addWidget(dialog)
    dialog.host_input.setText("192.168.1.99")

    dialog._on_accept()

    assert dialog.result() != AddServerDialog.DialogCode.Accepted
    assert "Could not reach server" in dialog.status_label.text()


def test_blank_host_is_rejected(qtbot) -> None:
    dialog = AddServerDialog()
    qtbot.addWidget(dialog)

    dialog._on_accept()

    assert dialog.result() != AddServerDialog.DialogCode.Accepted
    assert "Host is required" in dialog.status_label.text()
