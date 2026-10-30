"""Tests for team chats: every team has a group chat that follows its members.

The rules under test, from ``conversation_service.sync_team_conversation`` and
its callers in ``team_service``:

* creating a team creates its chat, named after the team, lead as its admin;
* adding, removing and re-leading members and renaming the team update it;
* nobody changes who is in a team chat by hand (409) -- not even its admin;
* deleting the team keeps the chat, as an ordinary group chat;
* the start-up back-fill gives older teams a chat and is safe to repeat.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from server.models.conversation import Conversation, ConversationParticipant
from server.models.team import Team
from server.services import team_service
from shared.chat_enums import ParticipantRole
from tests.server.conftest import Account


def _team_chat(client: TestClient, account: Account, team_id: int) -> dict | None:
    """The team's chat as ``account`` sees it in their conversation list, or None."""
    response = client.get("/conversations", headers=account.headers)
    assert response.status_code == 200, response.text
    return next((c for c in response.json() if c["team_id"] == team_id), None)


def _roles(chat: dict) -> dict[int, str]:
    return {p["user_id"]: p["role"] for p in chat["participants"]}


# ------------------------------------------------------------------- creation


def test_creating_a_team_creates_its_chat_with_the_lead_as_admin(
    client: TestClient, lead: Account
) -> None:
    team_id = client.post("/teams", json={"name": "Alpha"}, headers=lead.headers).json()["id"]

    chat = _team_chat(client, lead, team_id)

    assert chat is not None
    assert chat["kind"] == "group"
    assert chat["name"] == "Alpha"
    assert _roles(chat) == {lead.id: ParticipantRole.ADMIN.value}


def test_a_team_member_sees_the_chat_and_can_post_in_it(
    client: TestClient, team: dict, member: Account
) -> None:
    chat = _team_chat(client, member, team["id"])
    assert chat is not None

    response = client.post(
        f"/conversations/{chat['id']}/messages",
        json={"body": "hello team", "client_token": "t-1"},
        headers=member.headers,
    )

    assert response.status_code in (200, 201), response.text


def test_an_outsider_does_not_see_the_team_chat(
    client: TestClient, team: dict, outsider: Account
) -> None:
    assert _team_chat(client, outsider, team["id"]) is None


def test_an_admin_who_is_not_on_the_team_is_not_in_its_chat(
    client: TestClient, team: dict, admin: Account
) -> None:
    assert _team_chat(client, admin, team["id"]) is None


def test_ordinary_chats_have_no_team(client: TestClient, lead: Account, member: Account) -> None:
    response = client.post(
        "/conversations/direct", json={"other_user_id": member.id}, headers=lead.headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["team_id"] is None


# ------------------------------------------------------- following the team


def test_adding_a_member_adds_them_to_the_chat(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    chat = _team_chat(client, lead, team["id"])

    assert _roles(chat) == {
        lead.id: ParticipantRole.ADMIN.value,
        member.id: ParticipantRole.MEMBER.value,
    }


def test_removing_a_member_removes_them_from_the_chat(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    response = client.delete(f"/teams/{team['id']}/members/{member.id}", headers=lead.headers)
    assert response.status_code == 204, response.text

    assert _team_chat(client, member, team["id"]) is None
    assert set(_roles(_team_chat(client, lead, team["id"]))) == {lead.id}


def test_leaving_the_team_leaves_its_chat(client: TestClient, team: dict, member: Account) -> None:
    response = client.delete(f"/teams/{team['id']}/members/{member.id}", headers=member.headers)
    assert response.status_code == 204, response.text

    assert _team_chat(client, member, team["id"]) is None


def test_handing_over_the_lead_moves_the_chat_admin(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    response = client.put(
        f"/teams/{team['id']}/lead", json={"user_id": member.id}, headers=lead.headers
    )
    assert response.status_code == 200, response.text

    assert _roles(_team_chat(client, lead, team["id"])) == {
        lead.id: ParticipantRole.MEMBER.value,
        member.id: ParticipantRole.ADMIN.value,
    }


def test_renaming_the_team_renames_its_chat(client: TestClient, team: dict, lead: Account) -> None:
    response = client.patch(f"/teams/{team['id']}", json={"name": "Beta"}, headers=lead.headers)
    assert response.status_code == 200, response.text

    assert _team_chat(client, lead, team["id"])["name"] == "Beta"


def test_a_refused_team_change_leaves_the_chat_alone(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    client.post("/teams", json={"name": "Beta"}, headers=lead.headers)

    response = client.patch(f"/teams/{team['id']}", json={"name": "beta"}, headers=lead.headers)

    assert response.status_code == 409, response.text
    assert _team_chat(client, lead, team["id"])["name"] == "Alpha"


# ------------------------------------------------------ no changes by hand


def test_the_chat_admin_cannot_add_someone_by_hand(
    client: TestClient, team: dict, lead: Account, outsider: Account
) -> None:
    chat = _team_chat(client, lead, team["id"])

    response = client.post(
        f"/conversations/{chat['id']}/participants",
        json={"user_id": outsider.id},
        headers=lead.headers,
    )

    assert response.status_code == 409, response.text
    assert "team" in response.json()["detail"]
    assert _team_chat(client, outsider, team["id"]) is None


def test_the_chat_admin_cannot_remove_someone_by_hand(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    chat = _team_chat(client, lead, team["id"])

    response = client.delete(
        f"/conversations/{chat['id']}/participants/{member.id}", headers=lead.headers
    )

    assert response.status_code == 409, response.text
    assert _team_chat(client, member, team["id"]) is not None


def test_a_member_cannot_leave_the_team_chat_without_leaving_the_team(
    client: TestClient, team: dict, member: Account
) -> None:
    chat = _team_chat(client, member, team["id"])

    response = client.delete(
        f"/conversations/{chat['id']}/participants/{member.id}", headers=member.headers
    )

    assert response.status_code == 409, response.text


def test_the_chat_admin_cannot_change_roles_by_hand(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    chat = _team_chat(client, lead, team["id"])

    response = client.put(
        f"/conversations/{chat['id']}/participants/{member.id}/role",
        json={"role": ParticipantRole.ADMIN.value},
        headers=lead.headers,
    )

    assert response.status_code == 409, response.text


def test_a_non_participant_still_gets_403_not_the_team_chat_message(
    client: TestClient, team: dict, lead: Account, outsider: Account
) -> None:
    chat = _team_chat(client, lead, team["id"])

    response = client.post(
        f"/conversations/{chat['id']}/participants",
        json={"user_id": outsider.id},
        headers=outsider.headers,
    )

    assert response.status_code == 403, response.text


# ------------------------------------------------------------------- delete


def test_deleting_the_team_keeps_its_chat_as_an_ordinary_group(
    client: TestClient, team: dict, lead: Account, member: Account
) -> None:
    chat_id = _team_chat(client, lead, team["id"])["id"]

    response = client.delete(f"/teams/{team['id']}", headers=lead.headers)
    assert response.status_code == 204, response.text

    response = client.get(f"/conversations/{chat_id}", headers=member.headers)
    assert response.status_code == 200, response.text
    assert response.json()["team_id"] is None
    assert set(_roles(response.json())) == {lead.id, member.id}


def test_a_new_team_with_the_old_name_gets_a_fresh_chat(
    client: TestClient, team: dict, lead: Account
) -> None:
    old_chat_id = _team_chat(client, lead, team["id"])["id"]
    client.delete(f"/teams/{team['id']}", headers=lead.headers)

    new_id = client.post("/teams", json={"name": "Alpha"}, headers=lead.headers).json()["id"]

    assert _team_chat(client, lead, new_id)["id"] != old_chat_id


# ---------------------------------------------------------- start-up back-fill


def _strip_team_chats(session_factory: sessionmaker[Session]) -> None:
    """Make the database look like it did before team chats existed."""
    with session_factory() as db:
        for conversation in db.scalars(
            select(Conversation).where(Conversation.team_id.isnot(None))
        ):
            db.delete(conversation)
        db.commit()


def test_the_back_fill_gives_an_older_team_its_chat(
    client: TestClient,
    team: dict,
    lead: Account,
    member: Account,
    session_factory: sessionmaker[Session],
) -> None:
    _strip_team_chats(session_factory)
    assert _team_chat(client, lead, team["id"]) is None

    with session_factory() as db:
        team_service.ensure_team_conversations(db)

    chat = _team_chat(client, member, team["id"])
    assert chat is not None
    assert _roles(chat) == {
        lead.id: ParticipantRole.ADMIN.value,
        member.id: ParticipantRole.MEMBER.value,
    }


def test_the_back_fill_repairs_drift_and_is_safe_to_repeat(
    client: TestClient,
    team: dict,
    lead: Account,
    outsider: Account,
    session_factory: sessionmaker[Session],
) -> None:
    chat_id = _team_chat(client, lead, team["id"])["id"]
    with session_factory() as db:
        # Someone slipped in by editing the database directly.
        db.add(ConversationParticipant(conversation_id=chat_id, user_id=outsider.id))
        db.commit()

    for _ in range(2):
        with session_factory() as db:
            team_service.ensure_team_conversations(db)

    with session_factory() as db:
        assert db.scalar(select(Team).where(Team.id == team["id"])) is not None
        chats = list(db.scalars(select(Conversation).where(Conversation.team_id == team["id"])))
        assert len(chats) == 1
        assert {p.user_id for p in chats[0].participants} == {m["id"] for m in team["members"]}
