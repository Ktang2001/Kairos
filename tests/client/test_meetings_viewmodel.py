"""Tests for the meeting actions (client/viewmodels/meetings_viewmodel.py) and
the Profile options they add to links (client/viewmodels/meeting_preferences.py).

No browser ever opens: ``open_url`` is replaced with a recorder.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import unquote

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from client.api_client import ApiError
from client.viewmodels.meeting_preferences import MeetingPreferences, is_safe_meeting_url
from client.viewmodels.meetings_viewmodel import (
    NO_BROWSER_MESSAGE,
    UNSAFE_LINK_MESSAGE,
    MeetingsViewModel,
)
from tests.client.meeting_data import make_meeting

ROOM = "https://meet.jit.si/Kairos-abc"


class _FakeClient:
    """Records calls; answers like the server would."""

    def __init__(self, join_url: str = ROOM) -> None:
        self.calls: list[tuple] = []
        self.join_url = join_url
        self.fail_with: str | None = None

    def _call(self, *args):
        self.calls.append(args)
        if self.fail_with:
            raise ApiError(self.fail_with, 409)

    def create_chat_meeting(self, conversation_id: int, **fields) -> dict:
        self._call("create_chat_meeting", conversation_id, fields)
        return make_meeting(id=11, conversation_id=conversation_id, title=fields["title"])

    def create_team_meeting(self, team_id: int, **fields) -> dict:
        self._call("create_team_meeting", team_id, fields)
        return make_meeting(id=12, team_id=team_id, title=fields["title"])

    def respond_to_meeting(self, meeting_id: int, response: str) -> dict:
        self._call("respond_to_meeting", meeting_id, response)
        return make_meeting(id=meeting_id, my_response=response)

    def update_meeting(self, meeting_id: int, **changes) -> dict:
        self._call("update_meeting", meeting_id, changes)
        return make_meeting(id=meeting_id, title=changes["title"])

    def cancel_meeting(self, meeting_id: int) -> dict:
        self._call("cancel_meeting", meeting_id)
        return make_meeting(id=meeting_id, state="cancelled")

    def meeting_join_link(self, meeting_id: int) -> str:
        self._call("meeting_join_link", meeting_id)
        return self.join_url

    def list_chat_meetings(self, conversation_id: int) -> list[dict]:
        self._call("list_chat_meetings", conversation_id)
        return [make_meeting(conversation_id=conversation_id)]

    def list_teams(self) -> list[dict]:
        self._call("list_teams")
        return [{"id": 1, "name": "Alpha"}]

    def get_server_info(self) -> dict:
        self._call("get_server_info")
        return {"display_name": "Kairos", "jitsi_base_url": "https://meet.jit.si"}


@pytest.fixture
def preferences(tmp_path: Path) -> MeetingPreferences:
    return MeetingPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))


@pytest.fixture
def client() -> _FakeClient:
    return _FakeClient()


@pytest.fixture
def vm(qtbot: QtBot, client: _FakeClient, preferences: MeetingPreferences) -> MeetingsViewModel:
    model = MeetingsViewModel(client, preferences, display_name="Max")
    model.opened: list[str] = []
    model.open_url = lambda url: model.opened.append(url) or True
    model.errors: list[str] = []
    model.error_changed.connect(model.errors.append)
    model.changed: list[dict] = []
    model.meeting_changed.connect(model.changed.append)
    return model


def _settle(qtbot: QtBot, vm: MeetingsViewModel) -> None:
    qtbot.waitUntil(lambda: not vm.busy, timeout=5000)


# ---------------------------------------------------------------- joining


def test_join_opens_the_link_with_your_name(qtbot: QtBot, vm: MeetingsViewModel) -> None:
    vm.join(7)
    qtbot.waitUntil(lambda: bool(vm.opened), timeout=5000)

    assert vm.opened == [f'{ROOM}#userInfo.displayName={"%22Max%22"}']


def test_join_adds_your_profile_options(
    qtbot: QtBot, vm: MeetingsViewModel, preferences: MeetingPreferences
) -> None:
    preferences.display_name = "Max (laptop)"
    preferences.start_muted = True
    preferences.camera_off = True

    vm.join(7)
    qtbot.waitUntil(lambda: bool(vm.opened), timeout=5000)

    base, fragment = vm.opened[0].split("#")
    assert base == ROOM
    options = dict(part.split("=", 1) for part in fragment.split("&"))
    assert json.loads(unquote(options["userInfo.displayName"])) == "Max (laptop)"
    assert options["config.startWithAudioMuted"] == "true"
    assert options["config.startWithVideoMuted"] == "true"


@pytest.mark.parametrize("name", ['Max "the" Tester', "A&B#c", "émile 名前", "x=1&config.y=2"])
def test_a_name_cannot_break_out_of_its_setting(name: str, preferences: MeetingPreferences) -> None:
    preferences.display_name = name

    fragment = preferences.join_url(ROOM, "ignored").split("#", 1)[1]

    assert fragment.count("&") == 0  # only the one option: the name
    key, value = fragment.split("=", 1)
    assert key == "userInfo.displayName"
    assert json.loads(unquote(value)) == name


def test_with_no_name_or_options_the_link_is_left_alone(preferences: MeetingPreferences) -> None:
    assert preferences.join_url(ROOM, "") == ROOM


def test_an_existing_fragment_is_replaced(preferences: MeetingPreferences) -> None:
    url = preferences.join_url(f"{ROOM}#config.evil=true", "Max")

    assert "evil" not in url


@pytest.mark.parametrize(
    "url",
    ["http://meet.jit.si/room", "file:///etc/passwd", "javascript:alert(1)", "https://", "room"],
)
def test_a_link_that_isnt_https_is_never_opened(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel, url: str
) -> None:
    client.join_url = url

    vm.join(7)
    _settle(qtbot, vm)

    assert vm.opened == []
    assert vm.errors[-1] == UNSAFE_LINK_MESSAGE


def test_a_refused_join_shows_the_servers_reason(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel
) -> None:
    client.fail_with = "This meeting was cancelled"

    vm.join(7)
    _settle(qtbot, vm)

    assert vm.opened == []
    assert vm.errors[-1] == "This meeting was cancelled"


def test_no_browser_is_reported(qtbot: QtBot, vm: MeetingsViewModel) -> None:
    vm.open_url = lambda url: False

    vm.join(7)
    _settle(qtbot, vm)

    assert vm.errors[-1] == NO_BROWSER_MESSAGE


def test_is_safe_meeting_url() -> None:
    assert is_safe_meeting_url("https://meet.jit.si/Kairos-x")
    assert not is_safe_meeting_url("HTTP://meet.jit.si/x")
    assert not is_safe_meeting_url("")


# ---------------------------------------------------------------- creating


def test_an_instant_chat_meeting_is_joined_straight_away(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel
) -> None:
    vm.create_in_chat(
        3, title="Quick call", starts_at=None, duration_minutes=30, client_token="tok"
    )
    qtbot.waitUntil(lambda: bool(vm.opened), timeout=5000)

    name, conversation_id, fields = client.calls[0]
    assert (name, conversation_id) == ("create_chat_meeting", 3)
    assert fields == {
        "title": "Quick call",
        "starts_at": None,
        "duration_minutes": 30,
        "client_token": "tok",
        "reminder_minutes": [],
    }
    assert client.calls[1] == ("meeting_join_link", 11)
    assert [m["id"] for m in vm.changed] == [11]


def test_a_scheduled_team_meeting_is_not_joined(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel
) -> None:
    starts = datetime(2026, 12, 1, 9, 0, tzinfo=timezone(timedelta(hours=-6)))

    vm.create_for_team(1, title="Planning", starts_at=starts, duration_minutes=60, client_token="t")
    _settle(qtbot, vm)

    assert client.calls[0][2]["starts_at"] == "2026-12-01T09:00:00-06:00"
    assert vm.opened == []
    assert [m["id"] for m in vm.changed] == [12]


def test_a_naive_time_is_sent_as_this_computers_local_time(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel
) -> None:
    vm.create_for_team(
        1, title="P", starts_at=datetime(2026, 12, 1, 9, 0), duration_minutes=60, client_token="t"
    )
    _settle(qtbot, vm)

    sent = datetime.fromisoformat(client.calls[0][2]["starts_at"])
    assert sent.tzinfo is not None
    assert sent == datetime(2026, 12, 1, 9, 0).astimezone()


def test_a_refused_create_reports_and_changes_nothing(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel
) -> None:
    client.fail_with = "Only the team's members can start a meeting for it"

    vm.create_for_team(1, title="P", starts_at=None, duration_minutes=60, client_token="t")
    _settle(qtbot, vm)

    assert vm.changed == []
    assert vm.opened == []
    assert vm.errors[-1].startswith("Only the team's members")


# ---------------------------------------------------------------- replies


def test_replying_and_cancelling_announce_the_new_meeting(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel
) -> None:
    vm.respond(7, "tentative")
    _settle(qtbot, vm)
    vm.cancel(7)
    _settle(qtbot, vm)

    assert ("respond_to_meeting", 7, "tentative") in client.calls
    assert ("cancel_meeting", 7) in client.calls
    assert [m["my_response"] for m in vm.changed][:1] == ["tentative"]
    assert vm.changed[-1]["state"] == "cancelled"


def test_loading_a_chats_meetings_reports_them_by_chat(qtbot: QtBot, vm: MeetingsViewModel) -> None:
    loaded = []
    vm.chat_meetings_loaded.connect(lambda cid, meetings: loaded.append((cid, meetings)))

    vm.load_chat_meetings(3)
    qtbot.waitUntil(lambda: bool(loaded), timeout=5000)

    assert loaded[0][0] == 3
    assert loaded[0][1][0]["id"] == 7
    assert not vm.busy  # background polling doesn't count as busy


def test_open_jitsi_home_opens_the_servers_jitsi_site(qtbot: QtBot, vm: MeetingsViewModel) -> None:
    vm.open_jitsi_home()
    qtbot.waitUntil(lambda: bool(vm.opened), timeout=5000)

    assert vm.opened == ["https://meet.jit.si"]


def test_busy_counts_overlapping_requests(qtbot: QtBot, vm: MeetingsViewModel) -> None:
    states = []
    vm.busy_changed.connect(states.append)

    vm.respond(7, "accepted")
    vm.respond(7, "declined")
    _settle(qtbot, vm)

    assert states == [True, False]


# ---------------------------------------------------------------- preferences


def test_preferences_are_kept_on_this_computer(tmp_path: Path) -> None:
    path = str(tmp_path / "prefs.ini")
    first = MeetingPreferences(QSettings(path, QSettings.Format.IniFormat))
    first.display_name = "  Max  "
    first.start_muted = True

    again = MeetingPreferences(QSettings(path, QSettings.Format.IniFormat))

    assert again.display_name == "Max"
    assert again.start_muted is True
    assert again.camera_off is False


def test_a_very_long_name_is_cut(preferences: MeetingPreferences) -> None:
    preferences.display_name = "x" * 500

    assert len(preferences.display_name) == 100


def test_editing_sends_the_new_details_with_an_offset(
    qtbot: QtBot, client: _FakeClient, vm: MeetingsViewModel
) -> None:
    starts = datetime(2026, 12, 1, 9, 0, tzinfo=timezone(timedelta(hours=-6)))

    vm.edit(7, title="Retro", starts_at=starts, duration_minutes=45, reminder_minutes=[60, 0])
    _settle(qtbot, vm)

    assert client.calls[0] == (
        "update_meeting",
        7,
        {
            "title": "Retro",
            "starts_at": "2026-12-01T09:00:00-06:00",
            "duration_minutes": 45,
            "reminder_minutes": [0, 60],
        },
    )
    assert vm.changed[-1]["title"] == "Retro"
