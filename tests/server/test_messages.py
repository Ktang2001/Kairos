from fastapi.testclient import TestClient

from server.main import app

client = TestClient(app)


def test_send_and_list_message() -> None:
    response = client.post("/messages", json={"sender": "client", "content": "hello"})
    assert response.status_code == 200
    body = response.json()
    assert body["sender"] == "client"
    assert body["content"] == "hello"
    assert "id" in body

    response = client.get("/messages")
    assert response.status_code == 200
    messages = response.json()
    assert any(m["content"] == "hello" for m in messages)
