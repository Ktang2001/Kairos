import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.server.conftest import auth_headers


def _start_direct_conversation(client: TestClient, alice, other) -> dict:
    return client.post(
        "/conversations/direct", json={"other_user_id": other.id}, headers=auth_headers(alice.token)
    ).json()


def test_websocket_receives_broadcast_on_new_message(client: TestClient, make_user) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    conversation = _start_direct_conversation(client, alice, bob)

    with client.websocket_connect(f"/ws/chat?token={alice.token}") as alice_ws:
        response = client.post(
            f"/conversations/{conversation['id']}/messages",
            json={"body": "hi alice"},
            headers=auth_headers(bob.token),
        )
        assert response.status_code == 200

        event = alice_ws.receive_json()
        assert event["type"] == "chat_message"
        assert event["conversation_id"] == conversation["id"]
        assert event["message"]["body"] == "hi alice"


def test_non_participant_does_not_receive_other_conversations_messages(
    client: TestClient, make_user
) -> None:
    alice = make_user("Alice", "alice@example.com")
    bob = make_user("Bob", "bob@example.com")
    mallory = make_user("Mallory", "mallory@example.com")

    private_conversation = _start_direct_conversation(client, alice, bob)
    mallory_conversation = _start_direct_conversation(client, alice, mallory)

    with client.websocket_connect(f"/ws/chat?token={mallory.token}") as mallory_ws:
        client.post(
            f"/conversations/{private_conversation['id']}/messages",
            json={"body": "not for mallory"},
            headers=auth_headers(alice.token),
        )
        client.post(
            f"/conversations/{mallory_conversation['id']}/messages",
            json={"body": "for mallory"},
            headers=auth_headers(alice.token),
        )

        # If the private-conversation broadcast had leaked to mallory, it would be
        # first in her queue (events arrive in send order) - asserting this canary
        # event is first proves it never did, without ever blocking on an absence.
        event = mallory_ws.receive_json()
        assert event["message"]["body"] == "for mallory"


def test_websocket_rejects_unknown_token(client: TestClient) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/chat?token=not-a-real-token"),
    ):
        pass
    assert exc_info.value.code == 4401
