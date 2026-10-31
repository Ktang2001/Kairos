"""Tests for meetings (server/services/meeting_service.py, server/api/meetings.py).

The rules under test:

* anyone in a chat starts or schedules a meeting there and is its host; a team
  meeting is held in the team's chat, so any team member may start one;
* a meeting is visible to the people in its chat and, for a team meeting, to
  admins; to anyone else it does not exist (404);
* invitees accept / tentatively accept / decline, and can change their mind;
  the host doesn't reply to their own meeting;
* only the host or an admin cancels; cancelling posts a chat message;
* a cancelled or finished meeting can't be replied to or joined;
* every meeting keeps the Jitsi address it was made with.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from server.services.task_service import utcnow
from shared.meetings import MAX_DURATION_MINUTES, MIN_DURATION_MINUTES
from tests.server.conftest import Account


def _iso(moment: datetime) -> str:
    return moment.isoformat()


def _in(minutes: int) -> str:
    """A start time ``minutes`` from now, time-zone aware."""
    return _iso(datetime.now(UTC) + timedelta(minutes=minutes))


def _team_chat_id(client: TestClient, account: Account, team_id: int) -> int:
    chats = client.get("/conversations", headers=account.headers).json()
    return next(c["id"] for c in chats if c["team_id"] == team_id)


def _team_meeting(client: TestClient, account: Account, team_id: int, **fields) -> dict:
    response = client.post(
        f"/teams/{team_id}/meetings",
        json={"title": "Stand-up", "starts_at": _in(60), **fields},
        headers=account.headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _private_group(client: TestClient, creator: Account, *others: Account) -> int:
    response = client.post(
        "/conversations/group",
        json={"name": "Side chat", "member_user_ids": [o.id for o in others]},
        headers=creator.headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _later(monkeypatch: pytest.MonkeyPatch, minutes: int) -> None:
    """Move the meeting routes' clock ``minutes`` forward."""
    moved = utcnow() + timedelta(minutes=minutes)
    monkeypatch.setattr("server.api.meetings.utcnow", lambda: moved)


@pytest.fixture
def meeting(client: TestClient, team: dict, member: Account) -> dict:
    """A team meeting in an hour, hosted by ``member``; ``lead`` is invited."""
    return _team_meeting(client, member, team["id"])


# --------------------------------------------------------------------- create


def test_a_team_member_schedules_a_team_meeting_and_hosts_it(
    client: TestClient, team: dict, member: Account
) -> None:
    starts = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=2)

    body = _team_meeting(
        client, member, team["id"], title="Planning", starts_at=_iso(starts), duration_minutes=30
    )

    assert body["title"] == "Planning"
    assert body["team_id"] == team["id"]
    assert body["team_name"] == "Alpha"
    assert body["host"]["id"] == member.id
    assert body["is_host"] is True
    assert body["can_cancel"] is True
    assert body["state"] == "scheduled"
    assert datetime.fromisoformat(body["starts_at"]) == starts
    assert datetime.fromisoformat(body["ends_at"]) == starts + timedelta(minutes=30)
    assert body["my_response"] is None
    assert body["counts"] == {"accepted": 0, "tentative": 0, "declined": 0, "no_response": 1}


def test_times_come_back_in_utc_with_an_offset(
    client: TestClient, team: dict, member: Account
) -> None:
    # Sent as 10:00 at UTC-5, i.e. 15:00 UTC.
    body = _team_meeting(client, member, team["id"], starts_at="2199-06-01T10:00:00-05:00")

    returned = datetime.fromisoformat(body["starts_at"])
    assert returned.utcoffset() == timedelta(0)
    assert returned == datetime(2199, 6, 1, 15, 0, tzinfo=UTC)


def test_no_start_time_means_start_now(client: TestClient, team: dict, member: Account) -> None:
    before = datetime.now(UTC) - timedelta(seconds=5)

    body = _team_meeting(client, member, team["id"], starts_at=None)

    assert before <= datetime.fromisoformat(body["starts_at"]) <= datetime.now(UTC)
    assert body["has_ended"] is False


def test_a_team_meeting_is_announced_in_the_team_chat(
    client: TestClient, team: dict, lead: Account, meeting: dict
) -> None:
    chat_id = _team_chat_id(client, lead, team["id"])

    messages = client.get(f"/conversations/{chat_id}/messages", headers=lead.headers).json()

    assert messages[-1]["meeting_id"] == meeting["id"]
    assert messages[-1]["body"] == "Scheduled a meeting: Stand-up"
    assert meeting["conversation_id"] == chat_id


def test_anyone_in_a_chat_can_start_a_meeting_in_it(
    client: TestClient, member: Account, outsider: Account
) -> None:
    chat_id = _private_group(client, member, outsider)

    response = client.post(
        f"/conversations/{chat_id}/meetings",
        json={"title": "Quick call"},
        headers=outsider.headers,
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["team_id"] is None
    assert body["host"]["id"] == outsider.id
    messages = client.get(f"/conversations/{chat_id}/messages", headers=member.headers).json()
    assert messages[-1]["body"] == "Started a meeting: Quick call"


def test_someone_outside_a_chat_cannot_start_a_meeting_in_it(
    client: TestClient, member: Account, lead: Account, outsider: Account
) -> None:
    chat_id = _private_group(client, member, lead)

    response = client.post(
        f"/conversations/{chat_id}/meetings", json={"title": "Sneaky"}, headers=outsider.headers
    )

    assert response.status_code == 404, response.text


def test_an_outsider_cannot_start_a_team_meeting(
    client: TestClient, team: dict, outsider: Account
) -> None:
    response = client.post(
        f"/teams/{team['id']}/meetings", json={"title": "Sneaky"}, headers=outsider.headers
    )

    assert response.status_code == 404, response.text


def test_an_admin_who_is_not_on_the_team_cannot_start_a_team_meeting(
    client: TestClient, team: dict, admin: Account
) -> None:
    response = client.post(
        f"/teams/{team['id']}/meetings", json={"title": "Audit"}, headers=admin.headers
    )

    assert response.status_code == 403, response.text


def test_sending_the_same_client_token_twice_makes_one_meeting(
    client: TestClient, team: dict, member: Account
) -> None:
    first = _team_meeting(client, member, team["id"], client_token="abc123")
    second = _team_meeting(client, member, team["id"], client_token="abc123")

    assert second["id"] == first["id"]
    upcoming = client.get("/meetings/upcoming", headers=member.headers).json()
    assert [m["id"] for m in upcoming] == [first["id"]]


def test_a_client_token_already_used_by_a_text_message_is_refused(
    client: TestClient, team: dict, member: Account
) -> None:
    chat_id = _team_chat_id(client, member, team["id"])
    client.post(
        f"/conversations/{chat_id}/messages",
        json={"body": "hi", "client_token": "tok"},
        headers=member.headers,
    )

    response = client.post(
        f"/teams/{team['id']}/meetings",
        json={"title": "Stand-up", "client_token": "tok"},
        headers=member.headers,
    )

    assert response.status_code == 409, response.text


def test_each_meeting_gets_its_own_unguessable_room(
    client: TestClient, team: dict, member: Account
) -> None:
    links = set()
    for _ in range(3):
        meeting = _team_meeting(client, member, team["id"])
        url = client.get(f"/meetings/{meeting['id']}/join", headers=member.headers).json()["url"]
        links.add(url)

    assert len(links) == 3
    for url in links:
        room = url.removeprefix("https://meet.jit.si/")
        assert room.startswith("Kairos-")
        assert len(room) >= len("Kairos-") + 20


# ----------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "fields",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "\u200b\u200b"},
        {"title": "x" * 201},
        {"duration_minutes": MIN_DURATION_MINUTES - 1},
        {"duration_minutes": MAX_DURATION_MINUTES + 1},
        {"duration_minutes": 0},
        {"duration_minutes": -30},
        # No time zone: 14:00 where? Refused rather than guessed.
        {"starts_at": "2199-06-01T14:00:00"},
        {"starts_at": "not a time"},
        {"client_token": "x" * 101},
    ],
)
def test_bad_meeting_details_are_refused(
    client: TestClient, team: dict, member: Account, fields: dict
) -> None:
    response = client.post(
        f"/teams/{team['id']}/meetings",
        json={"title": "Stand-up", **fields},
        headers=member.headers,
    )

    assert response.status_code == 422, response.text


def test_a_start_in_the_past_is_refused(client: TestClient, team: dict, member: Account) -> None:
    response = client.post(
        f"/teams/{team['id']}/meetings",
        json={"title": "Stand-up", "starts_at": _in(-60)},
        headers=member.headers,
    )

    assert response.status_code == 422, response.text
    assert "past" in response.json()["detail"]


def test_a_start_a_minute_ago_is_accepted(client: TestClient, team: dict, member: Account) -> None:
    _team_meeting(client, member, team["id"], starts_at=_in(-1))


def test_a_start_beyond_the_date_range_is_refused(
    client: TestClient, team: dict, member: Account
) -> None:
    response = client.post(
        f"/teams/{team['id']}/meetings",
        json={"title": "Stand-up", "starts_at": "2300-01-01T00:00:00+00:00"},
        headers=member.headers,
    )

    assert response.status_code == 422, response.text


def test_a_title_with_control_characters_is_cleaned(
    client: TestClient, team: dict, member: Account
) -> None:
    body = _team_meeting(client, member, team["id"], title="  <b>Stand\u200b-up</b>\x07  ")

    # Cleaned of invisible characters but not of the angle brackets: the
    # client shows titles as plain text, so markup is just characters.
    assert body["title"] == "<b>Stand-up</b>"


# ----------------------------------------------------------------- visibility


def test_an_invitee_sees_the_meeting(client: TestClient, lead: Account, meeting: dict) -> None:
    response = client.get(f"/meetings/{meeting['id']}", headers=lead.headers)

    assert response.status_code == 200, response.text
    assert response.json()["is_host"] is False
    assert response.json()["can_cancel"] is False


def test_an_outsider_gets_404_for_a_team_meeting(
    client: TestClient, outsider: Account, meeting: dict
) -> None:
    for method, url in [
        ("get", f"/meetings/{meeting['id']}"),
        ("get", f"/meetings/{meeting['id']}/join"),
        ("post", f"/meetings/{meeting['id']}/cancel"),
    ]:
        response = client.request(method, url, headers=outsider.headers)
        assert response.status_code == 404, (url, response.text)
    response = client.put(
        f"/meetings/{meeting['id']}/response",
        json={"response": "accepted"},
        headers=outsider.headers,
    )
    assert response.status_code == 404, response.text


def test_an_admin_sees_a_team_meeting_without_being_on_the_team(
    client: TestClient, admin: Account, meeting: dict
) -> None:
    response = client.get(f"/meetings/{meeting['id']}", headers=admin.headers)

    assert response.status_code == 200, response.text
    assert response.json()["can_cancel"] is True
    upcoming = client.get("/meetings/upcoming", headers=admin.headers).json()
    assert [m["id"] for m in upcoming] == [meeting["id"]]


def test_an_admin_does_not_see_a_meeting_in_someone_elses_private_chat(
    client: TestClient, member: Account, outsider: Account, admin: Account
) -> None:
    chat_id = _private_group(client, member, outsider)
    meeting = client.post(
        f"/conversations/{chat_id}/meetings", json={"title": "Private"}, headers=member.headers
    ).json()

    assert client.get(f"/meetings/{meeting['id']}", headers=admin.headers).status_code == 404
    assert client.get("/meetings/upcoming", headers=admin.headers).json() == []


def test_someone_removed_from_the_team_loses_its_meetings(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    meeting = _team_meeting(client, lead, team["id"])
    client.delete(f"/teams/{team['id']}/members/{member.id}", headers=lead.headers)

    assert client.get(f"/meetings/{meeting['id']}", headers=member.headers).status_code == 404
    assert client.get("/meetings/upcoming", headers=member.headers).json() == []


def test_someone_added_to_the_team_sees_its_upcoming_meetings(
    client: TestClient, team: dict, lead: Account, outsider: Account, meeting: dict
) -> None:
    client.post(
        f"/teams/{team['id']}/members", json={"email": outsider.email}, headers=lead.headers
    )

    upcoming = client.get("/meetings/upcoming", headers=outsider.headers).json()

    assert [m["id"] for m in upcoming] == [meeting["id"]]
    assert upcoming[0]["counts"]["no_response"] == 2


def test_a_deleted_teams_meetings_stay_with_its_chat_but_admins_lose_them(
    client: TestClient, team: dict, lead: Account, member: Account, admin: Account, meeting: dict
) -> None:
    assert client.delete(f"/teams/{team['id']}", headers=lead.headers).status_code == 204

    response = client.get(f"/meetings/{meeting['id']}", headers=member.headers)
    assert response.status_code == 200, response.text
    assert response.json()["team_id"] is None
    assert client.get(f"/meetings/{meeting['id']}", headers=admin.headers).status_code == 404


def test_a_chats_meetings_are_listed_for_its_cards(
    client: TestClient, team: dict, lead: Account, outsider: Account, meeting: dict
) -> None:
    chat_id = meeting["conversation_id"]

    response = client.get(f"/conversations/{chat_id}/meetings", headers=lead.headers)
    assert response.status_code == 200, response.text
    assert [m["id"] for m in response.json()] == [meeting["id"]]

    response = client.get(f"/conversations/{chat_id}/meetings", headers=outsider.headers)
    assert response.status_code == 404, response.text


# -------------------------------------------------------------------- replies


def test_an_invitee_accepts_then_changes_their_mind(
    client: TestClient, lead: Account, member: Account, meeting: dict
) -> None:
    url = f"/meetings/{meeting['id']}/response"

    first = client.put(url, json={"response": "accepted"}, headers=lead.headers)
    assert first.status_code == 200, first.text
    assert first.json()["my_response"] == "accepted"

    second = client.put(url, json={"response": "tentative"}, headers=lead.headers)
    assert second.json()["my_response"] == "tentative"
    assert second.json()["counts"] == {
        "accepted": 0,
        "tentative": 1,
        "declined": 0,
        "no_response": 0,
    }

    host_view = client.get(f"/meetings/{meeting['id']}", headers=member.headers).json()
    assert [(r["user"]["id"], r["response"]) for r in host_view["responses"]] == [
        (lead.id, "tentative")
    ]


def test_the_host_cannot_reply_to_their_own_meeting(
    client: TestClient, member: Account, meeting: dict
) -> None:
    response = client.put(
        f"/meetings/{meeting['id']}/response",
        json={"response": "declined"},
        headers=member.headers,
    )

    assert response.status_code == 409, response.text


@pytest.mark.parametrize("bad", ["maybe", "ACCEPTED", "", None])
def test_an_unknown_reply_is_refused(
    client: TestClient, lead: Account, meeting: dict, bad: str | None
) -> None:
    response = client.put(
        f"/meetings/{meeting['id']}/response", json={"response": bad}, headers=lead.headers
    )

    assert response.status_code == 422, response.text


def test_an_admin_viewer_can_reply_to_a_team_meeting(
    client: TestClient, admin: Account, meeting: dict
) -> None:
    response = client.put(
        f"/meetings/{meeting['id']}/response",
        json={"response": "accepted"},
        headers=admin.headers,
    )

    assert response.status_code == 200, response.text
    # Admins aren't in the team chat, so they aren't counted as invited.
    assert response.json()["counts"]["accepted"] == 0


# --------------------------------------------------------------------- cancel


def test_the_host_cancels_and_the_chat_is_told(
    client: TestClient, lead: Account, member: Account, meeting: dict
) -> None:
    response = client.post(f"/meetings/{meeting['id']}/cancel", headers=member.headers)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "cancelled"
    assert response.json()["cancelled_at"] is not None
    messages = client.get(
        f"/conversations/{meeting['conversation_id']}/messages", headers=lead.headers
    ).json()
    assert messages[-1]["body"] == "Cancelled the meeting: Stand-up"
    assert messages[-1]["sender_user_id"] == member.id


def test_an_invitee_cannot_cancel(client: TestClient, lead: Account, meeting: dict) -> None:
    response = client.post(f"/meetings/{meeting['id']}/cancel", headers=lead.headers)

    assert response.status_code == 403, response.text


def test_an_admin_can_cancel_a_team_meeting(
    client: TestClient, admin: Account, meeting: dict
) -> None:
    response = client.post(f"/meetings/{meeting['id']}/cancel", headers=admin.headers)

    assert response.status_code == 200, response.text
    assert response.json()["state"] == "cancelled"


def test_cancelling_twice_is_harmless_and_posts_one_notice(
    client: TestClient, member: Account, meeting: dict
) -> None:
    for _ in range(2):
        response = client.post(f"/meetings/{meeting['id']}/cancel", headers=member.headers)
        assert response.status_code == 200, response.text

    messages = client.get(
        f"/conversations/{meeting['conversation_id']}/messages", headers=member.headers
    ).json()
    assert [m["body"] for m in messages].count("Cancelled the meeting: Stand-up") == 1


def test_a_cancelled_meeting_cannot_be_joined_or_replied_to(
    client: TestClient, lead: Account, member: Account, meeting: dict
) -> None:
    client.post(f"/meetings/{meeting['id']}/cancel", headers=member.headers)

    join = client.get(f"/meetings/{meeting['id']}/join", headers=lead.headers)
    reply = client.put(
        f"/meetings/{meeting['id']}/response", json={"response": "accepted"}, headers=lead.headers
    )

    assert join.status_code == 409, join.text
    assert "cancelled" in join.json()["detail"]
    assert reply.status_code == 409, reply.text


def test_a_cancelled_meeting_leaves_the_upcoming_list(
    client: TestClient, lead: Account, member: Account, meeting: dict
) -> None:
    client.post(f"/meetings/{meeting['id']}/cancel", headers=member.headers)

    assert client.get("/meetings/upcoming", headers=lead.headers).json() == []
    # ...but stays in its chat, so the card can show "Cancelled".
    cards = client.get(
        f"/conversations/{meeting['conversation_id']}/meetings", headers=lead.headers
    ).json()
    assert [c["state"] for c in cards] == ["cancelled"]


# ---------------------------------------------------------------- time passing


def test_a_finished_meeting_cannot_be_joined_replied_to_or_cancelled(
    client: TestClient,
    lead: Account,
    member: Account,
    meeting: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The meeting starts in an hour and lasts an hour.
    _later(monkeypatch, 121)

    join = client.get(f"/meetings/{meeting['id']}/join", headers=lead.headers)
    reply = client.put(
        f"/meetings/{meeting['id']}/response", json={"response": "accepted"}, headers=lead.headers
    )
    cancel = client.post(f"/meetings/{meeting['id']}/cancel", headers=member.headers)

    for response in (join, reply, cancel):
        assert response.status_code == 409, response.text
        assert "ended" in response.json()["detail"]
    assert client.get("/meetings/upcoming", headers=lead.headers).json() == []
    assert client.get(f"/meetings/{meeting['id']}", headers=lead.headers).json()["has_ended"]


def test_a_meeting_under_way_is_still_upcoming_and_joinable(
    client: TestClient, lead: Account, meeting: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    _later(monkeypatch, 90)

    assert [m["id"] for m in client.get("/meetings/upcoming", headers=lead.headers).json()] == [
        meeting["id"]
    ]
    assert client.get(f"/meetings/{meeting['id']}/join", headers=lead.headers).status_code == 200


def test_upcoming_meetings_are_soonest_first(
    client: TestClient, team: dict, member: Account, lead: Account
) -> None:
    later = _team_meeting(client, member, team["id"], title="Later", starts_at=_in(300))
    sooner = _team_meeting(client, member, team["id"], title="Sooner", starts_at=_in(30))

    upcoming = client.get("/meetings/upcoming", headers=lead.headers).json()

    assert [m["id"] for m in upcoming] == [sooner["id"], later["id"]]


# ---------------------------------------------------------------- Jitsi link


def test_join_returns_the_jitsi_link(client: TestClient, lead: Account, meeting: dict) -> None:
    response = client.get(f"/meetings/{meeting['id']}/join", headers=lead.headers)

    assert response.status_code == 200, response.text
    assert response.json()["url"].startswith("https://meet.jit.si/Kairos-")


def test_changing_the_jitsi_address_keeps_old_meetings_links(
    client: TestClient, team: dict, member: Account, lead: Account, make_user, meeting: dict
) -> None:
    old_url = client.get(f"/meetings/{meeting['id']}/join", headers=lead.headers).json()["url"]
    admin = make_user("Root", "root@example.com", role_name="admin")

    response = client.put(
        "/server/info",
        json={"jitsi_base_url": "https://jitsi.example.org/meet/"},
        headers={"Authorization": f"Bearer {admin.token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["jitsi_base_url"] == "https://jitsi.example.org/meet"

    assert client.get(f"/meetings/{meeting['id']}/join", headers=lead.headers).json()["url"] == (
        old_url
    )
    newer = _team_meeting(client, member, team["id"])
    new_url = client.get(f"/meetings/{newer['id']}/join", headers=lead.headers).json()["url"]
    assert new_url.startswith("https://jitsi.example.org/meet/Kairos-")


@pytest.mark.parametrize(
    "bad",
    [
        "http://meet.jit.si",
        "meet.jit.si",
        "",
        "   ",
        "https://",
        "https://meet.jit.si?room=x",
        "https://meet.jit.si#x",
        "https://user:pass@meet.jit.si",
        "https://meet jit.si",
        "javascript:alert(1)",
        "file:///etc/passwd",
    ],
)
def test_a_bad_jitsi_address_is_refused(client: TestClient, make_user, bad: str) -> None:
    admin = make_user("Root", "root@example.com", role_name="admin")

    response = client.put(
        "/server/info",
        json={"jitsi_base_url": bad},
        headers={"Authorization": f"Bearer {admin.token}"},
    )

    assert response.status_code == 400, response.text
    assert client.get("/server/info").json()["jitsi_base_url"] == "https://meet.jit.si"


def test_only_an_admin_changes_the_jitsi_address(client: TestClient, member: Account) -> None:
    response = client.put(
        "/server/info", json={"jitsi_base_url": "https://evil.example"}, headers=member.headers
    )

    assert response.status_code == 403, response.text


# ---------------------------------------------------------------------- edit


def _edit(client: TestClient, account: Account, meeting_id: int, **fields):
    return client.patch(f"/meetings/{meeting_id}", json=fields, headers=account.headers)


def test_the_host_renames_and_changes_reminders_quietly(
    client: TestClient, lead: Account, member: Account, meeting: dict
) -> None:
    client.put(
        f"/meetings/{meeting['id']}/response", json={"response": "accepted"}, headers=lead.headers
    )

    response = _edit(client, member, meeting["id"], title="Daily sync", reminder_minutes=[60, 0])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Daily sync"
    assert body["reminder_minutes"] == [0, 60]
    assert body["counts"]["accepted"] == 1  # replies kept: same time
    messages = client.get(
        f"/conversations/{meeting['conversation_id']}/messages", headers=lead.headers
    ).json()
    assert not any("Moved" in (m["body"] or "") for m in messages)


def test_moving_a_meeting_tells_the_chat_and_clears_replies(
    client: TestClient, lead: Account, member: Account, meeting: dict
) -> None:
    client.put(
        f"/meetings/{meeting['id']}/response", json={"response": "accepted"}, headers=lead.headers
    )
    new_start = datetime.now(UTC).replace(microsecond=0) + timedelta(days=2)

    response = _edit(client, member, meeting["id"], starts_at=new_start.isoformat())

    assert response.status_code == 200, response.text
    body = response.json()
    assert datetime.fromisoformat(body["starts_at"]) == new_start
    assert body["counts"]["accepted"] == 0 and body["responses"] == []
    messages = client.get(
        f"/conversations/{meeting['conversation_id']}/messages", headers=lead.headers
    ).json()
    assert messages[-1]["body"] == "Moved the meeting: Stand-up - please reply again"


def test_making_it_longer_also_counts_as_moving_it(
    client: TestClient, member: Account, meeting: dict
) -> None:
    response = _edit(client, member, meeting["id"], duration_minutes=90)

    assert response.status_code == 200, response.text
    assert response.json()["duration_minutes"] == 90
    assert response.json()["ends_at"] != meeting["ends_at"]


def test_an_admin_can_edit_a_team_meeting(
    client: TestClient, admin: Account, meeting: dict
) -> None:
    assert _edit(client, admin, meeting["id"], title="Audit").status_code == 200


def test_an_invitee_cannot_edit(client: TestClient, lead: Account, meeting: dict) -> None:
    response = _edit(client, lead, meeting["id"], title="Hijacked")

    assert response.status_code == 403, response.text
    assert "change or cancel" in response.json()["detail"]


def test_an_outsider_gets_404_when_editing(
    client: TestClient, outsider: Account, meeting: dict
) -> None:
    assert _edit(client, outsider, meeting["id"], title="x").status_code == 404


def test_a_cancelled_meeting_cannot_be_edited(
    client: TestClient, member: Account, meeting: dict
) -> None:
    client.post(f"/meetings/{meeting['id']}/cancel", headers=member.headers)

    assert _edit(client, member, meeting["id"], title="Back on").status_code == 409


def test_a_meeting_cannot_be_moved_into_the_past(
    client: TestClient, member: Account, meeting: dict
) -> None:
    response = _edit(client, member, meeting["id"], starts_at=_in(-120))

    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "fields",
    [
        {"title": None},
        {"starts_at": None},
        {"duration_minutes": None},
        {"title": "  "},
        {"duration_minutes": 1},
        {"reminder_minutes": [7]},
        {"starts_at": "2199-06-01T14:00:00"},
    ],
)
def test_bad_edits_are_refused(
    client: TestClient, member: Account, meeting: dict, fields: dict
) -> None:
    assert _edit(client, member, meeting["id"], **fields).status_code == 422


# ------------------------------------------------------------------ reminders


def test_the_hosts_reminders_are_kept_sorted_without_repeats(
    client: TestClient, team: dict, member: Account, lead: Account
) -> None:
    body = _team_meeting(client, member, team["id"], reminder_minutes=[60, 0, 60, 15])

    assert body["reminder_minutes"] == [0, 15, 60]
    invitee_view = client.get(f"/meetings/{body['id']}", headers=lead.headers).json()
    assert invitee_view["reminder_minutes"] == [0, 15, 60]


def test_a_meeting_says_when_it_was_made(client: TestClient, team: dict, member: Account) -> None:
    before = datetime.now(UTC) - timedelta(seconds=5)

    body = _team_meeting(client, member, team["id"])

    # Clients use it so the host of an instant meeting isn't "reminded" of it.
    created = datetime.fromisoformat(body["created_at"])
    assert created.utcoffset() == timedelta(0)
    assert before <= created <= datetime.now(UTC) + timedelta(seconds=5)


def test_a_meeting_has_no_host_reminders_unless_set(client: TestClient, meeting: dict) -> None:
    assert meeting["reminder_minutes"] == []


def test_an_instant_meeting_drops_reminders(
    client: TestClient, team: dict, member: Account
) -> None:
    body = _team_meeting(client, member, team["id"], starts_at=None, reminder_minutes=[15])

    assert body["reminder_minutes"] == []


@pytest.mark.parametrize(
    "reminders", [[7], [-5], [1441], ["soon"], [0, 5, 10, 15, 30, 60, 120, 1440, 1440], None]
)
def test_bad_reminder_times_are_refused(
    client: TestClient, team: dict, member: Account, reminders
) -> None:
    response = client.post(
        f"/teams/{team['id']}/meetings",
        json={"title": "Stand-up", "starts_at": _in(60), "reminder_minutes": reminders},
        headers=member.headers,
    )

    assert response.status_code == 422, response.text


# ------------------------------------------------------------------ dashboard


def test_the_dashboard_lists_upcoming_meetings(
    client: TestClient, lead: Account, meeting: dict
) -> None:
    body = client.get("/dashboard", headers=lead.headers).json()

    assert body["overview"]["upcoming_meetings"] == 1
    assert [m["id"] for m in body["meetings"]] == [meeting["id"]]
    assert body["meetings"][0]["title"] == "Stand-up"


# ---------------------------------------------------------------------- login


@pytest.mark.parametrize(
    ("method", "url", "body"),
    [
        ("post", "/conversations/1/meetings", {"title": "x"}),
        ("post", "/teams/1/meetings", {"title": "x"}),
        ("get", "/conversations/1/meetings", None),
        ("get", "/meetings/upcoming", None),
        ("get", "/meetings/1", None),
        ("put", "/meetings/1/response", {"response": "accepted"}),
        ("post", "/meetings/1/cancel", None),
        ("get", "/meetings/1/join", None),
    ],
)
def test_every_meeting_route_requires_login(
    client: TestClient, method: str, url: str, body: dict | None
) -> None:
    response = client.request(method, url, json=body)

    assert response.status_code == 401, response.text
