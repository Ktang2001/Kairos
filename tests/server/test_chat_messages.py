from fastapi.testclient import TestClient

from tests.server.conftest import auth_headers


def _start_direct_conversation(client: TestClient, alice, bob) -> dict:
    return client.post(
        "/conversations/direct", json={"other_user_id": bob.id}, headers=auth_headers(alice.id)
    ).json()


def test_cursor_pagination_returns_only_messages_after_given_id(
    client: TestClient, make_user
) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"

    first = client.post(base_url, json={"body": "hello"}, headers=auth_headers(alice.id)).json()
    client.post(base_url, json={"body": "how are you"}, headers=auth_headers(bob.id))
    third = client.post(base_url, json={"body": "bye"}, headers=auth_headers(alice.id)).json()

    response = client.get(base_url, params={"after_id": first["id"]}, headers=auth_headers(bob.id))

    assert response.status_code == 200
    bodies = [m["body"] for m in response.json()]
    assert bodies == ["how are you", "bye"]
    assert response.json()[-1]["id"] == third["id"]


def test_duplicate_client_token_is_idempotent(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"

    first = client.post(
        base_url,
        json={"body": "retry me", "client_token": "outbox-1"},
        headers=auth_headers(alice.id),
    )
    second = client.post(
        base_url,
        json={"body": "retry me", "client_token": "outbox-1"},
        headers=auth_headers(alice.id),
    )

    assert first.json()["id"] == second.json()["id"]

    all_messages = client.get(base_url, headers=auth_headers(alice.id)).json()
    assert len(all_messages) == 1


def test_non_participant_cannot_read_or_post_messages(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    mallory = make_user("Mallory", "mallory@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"

    read_response = client.get(base_url, headers=auth_headers(mallory.id))
    post_response = client.post(base_url, json={"body": "hi"}, headers=auth_headers(mallory.id))

    assert read_response.status_code == 403
    assert post_response.status_code == 403


def test_empty_body_is_rejected(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"

    response = client.post(base_url, json={"body": "   "}, headers=auth_headers(alice.id))

    assert response.status_code == 400
