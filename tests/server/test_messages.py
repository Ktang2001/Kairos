"""Tests for the /messages smoke-test routes.

These use the ``client`` fixture from conftest.py, never a bare
``TestClient(app)``: that would write into the development database.

Both routes require login, and the sender is always the signed-in user's
name -- they were open, which let anyone on the network read every message
and post as anyone (found by the security audit).
"""

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from server.api.messages import MAX_MESSAGES_PER_REQUEST
from server.schemas.message import MAX_CONTENT_LENGTH


@pytest.fixture
def headers(auth_headers: Callable[..., dict[str, str]]) -> dict[str, str]:
    """Signed in as "Sam"."""
    return auth_headers(email="sam@example.com", name="Sam")


def _post(client: TestClient, headers: dict, content: str, **extra) -> dict:
    response = client.post("/messages", json={"content": content, **extra}, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ------------------------------------------------------------------- login


def test_sending_requires_login(client: TestClient) -> None:
    assert client.post("/messages", json={"content": "hello"}).status_code == 401


def test_reading_requires_login(client: TestClient, headers: dict) -> None:
    _post(client, headers, "private")
    response = client.get("/messages")
    assert response.status_code == 401
    assert "private" not in response.text


def test_an_invalid_token_cannot_read_or_send(client: TestClient) -> None:
    bad = {"Authorization": "Bearer not-a-token"}
    assert client.get("/messages", headers=bad).status_code == 401
    assert client.post("/messages", json={"content": "x"}, headers=bad).status_code == 401


# ------------------------------------------------------------------ sender


def test_the_sender_is_the_signed_in_user(client: TestClient, headers: dict) -> None:
    assert _post(client, headers, "hello")["sender"] == "Sam"


def test_a_sender_in_the_body_is_ignored(client: TestClient, headers: dict) -> None:
    """Posting as "Ada (Admin)" just posts as yourself."""
    body = _post(client, headers, "trust me", sender="Ada (Admin)")
    assert body["sender"] == "Sam"


def test_each_user_posts_under_their_own_name(
    client: TestClient, headers: dict, auth_headers: Callable[..., dict[str, str]]
) -> None:
    other = auth_headers(email="kaleb@example.com", name="Kaleb")
    _post(client, headers, "from sam")
    _post(client, other, "from kaleb")
    senders = {m["content"]: m["sender"] for m in client.get("/messages", headers=headers).json()}
    assert senders == {"from sam": "Sam", "from kaleb": "Kaleb"}


# ------------------------------------------------------------ content rules


def test_send_and_list_message(client: TestClient, headers: dict) -> None:
    body = _post(client, headers, "hello")
    assert body["content"] == "hello"
    assert "id" in body

    response = client.get("/messages", headers=headers)
    assert response.status_code == 200
    assert [m["content"] for m in response.json()] == ["hello"]


def test_messages_are_listed_newest_first(client: TestClient, headers: dict) -> None:
    for text in ("first", "second", "third"):
        _post(client, headers, text)
    contents = [m["content"] for m in client.get("/messages", headers=headers).json()]
    assert contents == ["third", "second", "first"]


def test_surrounding_whitespace_is_stripped(client: TestClient, headers: dict) -> None:
    assert _post(client, headers, "  hi  ")["content"] == "hi"


def test_html_is_stored_as_plain_text(client: TestClient, headers: dict) -> None:
    """Stored verbatim; it is the windows' job to show it as text, not render it."""
    payload = '<span style="font-size:60px">SERVER HACKED</span>'
    assert _post(client, headers, payload)["content"] == payload


@pytest.mark.parametrize(
    "payload",
    [{"content": ""}, {"content": "   "}, {}],
    ids=["empty-content", "blank-content", "no-content"],
)
def test_empty_or_missing_content_is_rejected(
    client: TestClient, headers: dict, payload: dict
) -> None:
    assert client.post("/messages", json=payload, headers=headers).status_code == 422


def test_content_at_the_limit_is_accepted(client: TestClient, headers: dict) -> None:
    _post(client, headers, "a" * MAX_CONTENT_LENGTH)


def test_content_over_the_limit_is_rejected(client: TestClient, headers: dict) -> None:
    response = client.post(
        "/messages", json={"content": "a" * (MAX_CONTENT_LENGTH + 1)}, headers=headers
    )
    assert response.status_code == 422


def test_rejected_messages_are_not_stored(client: TestClient, headers: dict) -> None:
    client.post("/messages", json={"content": ""}, headers=headers)
    assert client.get("/messages", headers=headers).json() == []


# ------------------------------------------------------------------- limit


def test_limit_caps_the_number_returned(client: TestClient, headers: dict) -> None:
    for i in range(5):
        _post(client, headers, f"m{i}")
    response = client.get("/messages", params={"limit": 2}, headers=headers)
    assert [m["content"] for m in response.json()] == ["m4", "m3"]


@pytest.mark.parametrize("limit", [0, -1, MAX_MESSAGES_PER_REQUEST + 1, 10_000_000])
def test_out_of_range_limit_is_rejected(client: TestClient, headers: dict, limit: int) -> None:
    # -1 matters most: SQLite reads LIMIT -1 as "no limit at all".
    response = client.get("/messages", params={"limit": limit}, headers=headers)
    assert response.status_code == 422


def test_non_numeric_limit_is_rejected(client: TestClient, headers: dict) -> None:
    response = client.get("/messages", params={"limit": "lots"}, headers=headers)
    assert response.status_code == 422


def test_max_limit_is_accepted(client: TestClient, headers: dict) -> None:
    response = client.get("/messages", params={"limit": MAX_MESSAGES_PER_REQUEST}, headers=headers)
    assert response.status_code == 200
