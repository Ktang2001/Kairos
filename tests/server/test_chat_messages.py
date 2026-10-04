from fastapi.testclient import TestClient
from sqlalchemy import text

from tests.server.conftest import auth_headers


def _start_direct_conversation(client: TestClient, alice, bob) -> dict:
    return client.post(
        "/conversations/direct", json={"other_user_id": bob.id}, headers=auth_headers(alice.token)
    ).json()


def test_cursor_pagination_returns_only_messages_after_given_id(
    client: TestClient, make_user
) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"

    first = client.post(base_url, json={"body": "hello"}, headers=auth_headers(alice.token)).json()
    client.post(base_url, json={"body": "how are you"}, headers=auth_headers(bob.token))
    third = client.post(base_url, json={"body": "bye"}, headers=auth_headers(alice.token)).json()

    response = client.get(
        base_url, params={"after_id": first["id"]}, headers=auth_headers(bob.token)
    )

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
        headers=auth_headers(alice.token),
    )
    second = client.post(
        base_url,
        json={"body": "retry me", "client_token": "outbox-1"},
        headers=auth_headers(alice.token),
    )

    assert first.json()["id"] == second.json()["id"]

    all_messages = client.get(base_url, headers=auth_headers(alice.token)).json()
    assert len(all_messages) == 1


def test_non_participant_cannot_read_or_post_messages(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    mallory = make_user("Mallory", "mallory@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"

    read_response = client.get(base_url, headers=auth_headers(mallory.token))
    post_response = client.post(base_url, json={"body": "hi"}, headers=auth_headers(mallory.token))

    assert read_response.status_code == 403
    assert post_response.status_code == 403


def test_message_body_is_encrypted_at_rest(client: TestClient, make_user, db_session) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"
    secret = "my bank PIN is 4471"

    created = client.post(base_url, json={"body": secret}, headers=auth_headers(alice.token)).json()

    # Raw SQL bypasses the ORM's EncryptedText TypeDecorator, reading exactly the
    # bytes actually stored on disk - proving this is really encrypted, not just
    # trusting the code that's supposed to encrypt it.
    raw_body = db_session.execute(
        text("SELECT body FROM chat_messages WHERE id = :id"), {"id": created["id"]}
    ).scalar_one()

    assert raw_body != secret.encode("utf-8")
    assert b"bank PIN" not in raw_body

    # Through the normal API (and thus the ORM), it still comes back as plaintext.
    fetched = client.get(base_url, headers=auth_headers(alice.token)).json()
    assert fetched[0]["body"] == secret


def test_empty_body_is_rejected(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)
    base_url = f"/conversations/{conversation['id']}/messages"

    response = client.post(base_url, json={"body": "   "}, headers=auth_headers(alice.token))

    assert response.status_code == 400
