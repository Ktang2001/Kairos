import httpx

from client.views.server_settings_page import ServerSettingsPage


class _Resp:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class _FakeApiClient:
    def __init__(self) -> None:
        self.updates: list[dict] = []
        self.forbidden = False

    def get_server_info(self) -> dict:
        return {"display_name": "Kairos Server", "max_upload_size_bytes": 50 * 1024 * 1024}

    def update_server_info(self, display_name=None, upload_root=None, max_upload_size_bytes=None):
        if self.forbidden:
            raise httpx.HTTPStatusError("forbidden", request=None, response=_Resp(403, {}))
        self.updates.append(
            {
                "display_name": display_name,
                "upload_root": upload_root,
                "max_upload_size_bytes": max_upload_size_bytes,
            }
        )
        return {}


def test_loads_current_display_name_and_max_size(qtbot):
    page = ServerSettingsPage(_FakeApiClient())
    qtbot.addWidget(page)

    assert page.display_name_input.text() == "Kairos Server"
    assert page.max_upload_mb_input.text() == "50"
    assert page.upload_root_input.text() == ""  # never prefilled - not exposed by the server


def test_blank_upload_root_sends_none(qtbot):
    api = _FakeApiClient()
    page = ServerSettingsPage(api)
    qtbot.addWidget(page)

    page.display_name_input.setText("New Name")
    page._on_save()

    assert api.updates[-1] == {
        "display_name": "New Name",
        "upload_root": None,
        "max_upload_size_bytes": 50 * 1024 * 1024,
    }


def test_setting_upload_root_sends_it(qtbot):
    api = _FakeApiClient()
    page = ServerSettingsPage(api)
    qtbot.addWidget(page)

    page.upload_root_input.setText("/srv/kairos/uploads")
    page._on_save()

    assert api.updates[-1]["upload_root"] == "/srv/kairos/uploads"
    assert page.upload_root_input.text() == ""  # cleared after a successful save


def test_non_numeric_max_size_shows_error(qtbot):
    api = _FakeApiClient()
    page = ServerSettingsPage(api)
    qtbot.addWidget(page)

    page.max_upload_mb_input.setText("not a number")
    page._on_save()

    assert "whole number" in page.status_label.text()
    assert api.updates == []


def test_forbidden_shows_friendly_error(qtbot):
    api = _FakeApiClient()
    api.forbidden = True
    page = ServerSettingsPage(api)
    qtbot.addWidget(page)

    page._on_save()

    assert "global admin access" in page.status_label.text()
