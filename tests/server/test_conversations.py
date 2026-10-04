from fastapi.testclient import TestClient

from tests.server.conftest import auth_headers


def test_create_direct_conversation_between_two_users(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")

    response = client.post(
        "/conversations/direct",
        json={"other_user_id": bob.id},
        headers=auth_headers(alice.token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "direct"
    participant_ids = {p["user_id"] for p in body["participants"]}
    assert participant_ids == {alice.id, bob.id}
    assert all(p["role"] == "member" for p in body["participants"])


def test_create_direct_conversation_is_idempotent_for_same_pair(
    client: TestClient, make_user
) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")

    first = client.post(
        "/conversations/direct", json={"other_user_id": bob.id}, headers=auth_headers(alice.token)
    )
    second = client.post(
        "/conversations/direct", json={"other_user_id": alice.id}, headers=auth_headers(bob.token)
    )

    assert first.json()["id"] == second.json()["id"]


def test_create_group_conversation_makes_creator_admin(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    carol = make_user("Carol", "carol@example.com")

    response = client.post(
        "/conversations/group",
        json={"name": "Project Team", "member_user_ids": [bob.id, carol.id]},
        headers=auth_headers(alice.token),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["kind"] == "group"
    assert body["name"] == "Project Team"
    roles = {p["user_id"]: p["role"] for p in body["participants"]}
    assert roles[alice.id] == "admin"
    assert roles[bob.id] == "member"
    assert roles[carol.id] == "member"


def test_group_chat_requires_admin_to_add_member(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    carol = make_user("Carol", "carol@example.com")

    group = client.post(
        "/conversations/group",
        json={"name": "Team", "member_user_ids": [bob.id]},
        headers=auth_headers(alice.token),
    ).json()

    denied = client.post(
        f"/conversations/{group['id']}/participants",
        json={"user_id": carol.id},
        headers=auth_headers(bob.token),
    )
    assert denied.status_code == 403

    allowed = client.post(
        f"/conversations/{group['id']}/participants",
        json={"user_id": carol.id},
        headers=auth_headers(alice.token),
    )
    assert allowed.status_code == 200
    participant_ids = {p["user_id"] for p in allowed.json()["participants"]}
    assert carol.id in participant_ids


def test_cannot_remove_or_demote_last_admin(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")

    group = client.post(
        "/conversations/group",
        json={"name": "Team", "member_user_ids": [bob.id]},
        headers=auth_headers(alice.token),
    ).json()

    remove_response = client.delete(
        f"/conversations/{group['id']}/participants/{alice.id}",
        headers=auth_headers(alice.token),
    )
    assert remove_response.status_code == 409

    demote_response = client.put(
        f"/conversations/{group['id']}/participants/{alice.id}/role",
        json={"role": "member"},
        headers=auth_headers(alice.token),
    )
    assert demote_response.status_code == 409


def test_non_participant_cannot_read_conversation(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    mallory = make_user("Mallory", "mallory@example.com")

    conversation = client.post(
        "/conversations/direct", json={"other_user_id": bob.id}, headers=auth_headers(alice.token)
    ).json()

    response = client.get(
        f"/conversations/{conversation['id']}", headers=auth_headers(mallory.token)
    )
    assert response.status_code == 403


def test_unknown_session_token_is_rejected(client: TestClient) -> None:
    response = client.get("/conversations", headers=auth_headers("not-a-real-token"))
    assert response.status_code == 401


def test_missing_auth_header_is_rejected(client: TestClient) -> None:
    response = client.get("/conversations")
    assert response.status_code == 401
