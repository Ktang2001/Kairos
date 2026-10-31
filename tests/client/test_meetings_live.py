"""Meetings end to end: the real client view model against the real API
(``live_server``), so the client and server agree on every request and
response shape, not just on what each side's own tests assume.

No browser opens: the view model's ``open_url`` records instead.
"""

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient
from client.viewmodels.meeting_preferences import MeetingPreferences
from client.viewmodels.meetings_viewmodel import MeetingsViewModel
from shared.roles import ROLE_PROJECT_LEAD
from tests.client.conftest import SETUP_TIMEOUT, TEST_PASSWORD, set_live_role, unique_email

WAIT_MS = 8000


def _client(live_server: str, name: str, role: str | None = None) -> ApiClient:
    email = unique_email(name.lower())
    body = httpx.post(
        f"{live_server}/auth/signup",
        json={"name": name, "email": email, "password": TEST_PASSWORD},
        timeout=SETUP_TIMEOUT,
    ).json()
    if role is not None:
        set_live_role(email, role)
    client = ApiClient(base_url=live_server, token=body["token"], user_id=body["id"])
    client.email = email
    return client


def _meetings(client: ApiClient, name: str) -> MeetingsViewModel:
    ini = Path(tempfile.mkdtemp()) / "prefs.ini"
    vm = MeetingsViewModel(
        client,
        MeetingPreferences(QSettings(str(ini), QSettings.Format.IniFormat)),
        display_name=name,
    )
    vm.opened = []
    vm.open_url = lambda url: vm.opened.append(url) or True
    vm.changed = []
    vm.meeting_changed.connect(vm.changed.append)
    vm.errors = []
    vm.error_changed.connect(lambda message: message and vm.errors.append(message))
    return vm


def test_schedule_reply_join_and_cancel_a_team_meeting(qtbot: QtBot, live_server: str) -> None:
    lena = _client(live_server, "Lena", ROLE_PROJECT_LEAD)
    max_ = _client(live_server, "Max")
    team = lena.create_team(f"Live {unique_email('t')}"[:90])
    lena.add_member(team["id"], max_.email)
    lena_vm, max_vm = _meetings(lena, "Lena"), _meetings(max_, "Max")

    # Lena schedules a team meeting for tomorrow, from the client.
    starts = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
    lena_vm.create_for_team(
        team["id"], title="Planning", starts_at=starts, duration_minutes=45, client_token="live-1"
    )
    qtbot.waitUntil(lambda: bool(lena_vm.changed), timeout=WAIT_MS)
    meeting = lena_vm.changed[-1]
    assert meeting["is_host"] and meeting["team_id"] == team["id"]
    assert datetime.fromisoformat(meeting["starts_at"]) == starts.astimezone()
    assert lena_vm.opened == []  # scheduled, not instant

    # Max sees it on his dashboard and in the team chat, and replies.
    dashboard = max_.get_dashboard()
    assert [m["id"] for m in dashboard["meetings"]] == [meeting["id"]]
    chat_meetings = max_.list_chat_meetings(meeting["conversation_id"])
    assert [m["title"] for m in chat_meetings] == ["Planning"]

    max_vm.respond(meeting["id"], "tentative")
    qtbot.waitUntil(lambda: bool(max_vm.changed), timeout=WAIT_MS)
    assert max_vm.changed[-1]["my_response"] == "tentative"
    assert lena.list_upcoming_meetings()[0]["counts"]["tentative"] == 1

    # Max joins: the browser would open the meet.jit.si room with his name.
    max_vm.join(meeting["id"])
    qtbot.waitUntil(lambda: bool(max_vm.opened), timeout=WAIT_MS)
    assert max_vm.opened[0].startswith("https://meet.jit.si/Kairos-")
    assert max_vm.opened[0].endswith("#userInfo.displayName=%22Max%22")

    # Lena cancels; Max's next Join is refused by the server.
    lena_vm.cancel(meeting["id"])
    qtbot.waitUntil(lambda: lena_vm.changed[-1]["state"] == "cancelled", timeout=WAIT_MS)
    max_vm.join(meeting["id"])
    qtbot.waitUntil(lambda: bool(max_vm.errors), timeout=WAIT_MS)
    assert max_vm.errors[-1] == "This meeting was cancelled"
    assert len(max_vm.opened) == 1


def test_an_instant_chat_meeting_opens_for_its_host(qtbot: QtBot, live_server: str) -> None:
    ada = _client(live_server, "Ada")
    bob = _client(live_server, "Bob")
    chat = ada.start_direct_conversation(bob.user_id)
    ada_vm = _meetings(ada, "Ada")

    ada_vm.create_in_chat(
        chat["id"], title="Quick call", starts_at=None, duration_minutes=15, client_token="live-2"
    )

    qtbot.waitUntil(lambda: bool(ada_vm.opened), timeout=WAIT_MS)
    assert ada_vm.opened[0].startswith("https://meet.jit.si/Kairos-")
    messages = bob.list_messages(chat["id"])
    assert messages[-1]["meeting_id"] == ada_vm.changed[-1]["id"]


def test_the_host_moves_a_meeting_and_replies_start_over(qtbot: QtBot, live_server: str) -> None:
    lena = _client(live_server, "Lena", ROLE_PROJECT_LEAD)
    max_ = _client(live_server, "Max")
    team = lena.create_team(f"Move {unique_email('t')}"[:90])
    lena.add_member(team["id"], max_.email)
    lena_vm = _meetings(lena, "Lena")
    starts = (datetime.now() + timedelta(days=1)).replace(second=0, microsecond=0)
    lena_vm.create_for_team(
        team["id"], title="Planning", starts_at=starts, duration_minutes=30, client_token="mv-1"
    )
    qtbot.waitUntil(lambda: bool(lena_vm.changed), timeout=WAIT_MS)
    meeting = lena_vm.changed[-1]
    max_.respond_to_meeting(meeting["id"], "accepted")

    later = starts + timedelta(hours=2)
    lena_vm.edit(meeting["id"], title="Planning", starts_at=later, duration_minutes=30)
    qtbot.waitUntil(lambda: len(lena_vm.changed) == 2, timeout=WAIT_MS)

    moved = max_.list_upcoming_meetings()[0]
    assert datetime.fromisoformat(moved["starts_at"]) == later.astimezone()
    assert moved["my_response"] is None
