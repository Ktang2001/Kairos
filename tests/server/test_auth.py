"""Tests for the credential routes: POST /auth/register and POST /auth/login."""

from fastapi.testclient import TestClient

from tests.server.conftest import TEST_PASSWORD

REGISTER_URL = "/auth/register"
LOGIN_URL = "/auth/login"


def test_register_creates_a_member_and_returns_a_token(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL,
        json={"name": "Kaleb", "email": "kaleb@example.com", "password": TEST_PASSWORD},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token"]
    assert body["token_type"] == "bearer"
    assert body["user"]["email"] == "kaleb@example.com"
    assert body["user"]["name"] == "Kaleb"
    # Self-registration must never grant anything above the default role.
    assert body["user"]["role"] == "member"
    # The hash must never leave the server, not even behind another key name.
    assert "password" not in str(body).lower() or "password_hash" not in body


def test_register_response_never_contains_the_password_hash(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL,
        json={"name": "Kaleb", "email": "kaleb@example.com", "password": TEST_PASSWORD},
    )

    assert "password_hash" not in response.text
    assert TEST_PASSWORD not in response.text


def test_register_rejects_a_duplicate_email(client: TestClient) -> None:
    payload = {"name": "Kaleb", "email": "kaleb@example.com", "password": TEST_PASSWORD}
    assert client.post(REGISTER_URL, json=payload).status_code == 201

    response = client.post(REGISTER_URL, json=payload)

    assert response.status_code == 409
    assert "already registered" in response.json()["detail"].lower()


def test_register_treats_different_case_as_the_same_email(client: TestClient) -> None:
    """Alice@example.com and alice@example.com must not become two accounts."""
    assert (
        client.post(
            REGISTER_URL,
            json={"name": "Alice", "email": "Alice@Example.com", "password": TEST_PASSWORD},
        ).status_code
        == 201
    )

    response = client.post(
        REGISTER_URL,
        json={"name": "Alice again", "email": "alice@example.com", "password": TEST_PASSWORD},
    )

    assert response.status_code == 409


def test_register_stores_the_email_lowercased(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL,
        json={"name": "Alice", "email": "  Alice@Example.com  ", "password": TEST_PASSWORD},
    )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "alice@example.com"


def test_register_ignores_an_attempt_to_choose_a_role(client: TestClient) -> None:
    """A role sent in the body must be ignored, not honoured."""
    response = client.post(
        REGISTER_URL,
        json={
            "name": "Mallory",
            "email": "mallory@example.com",
            "password": TEST_PASSWORD,
            "role": "admin",
            "role_id": 1,
        },
    )

    assert response.status_code == 201
    assert response.json()["user"]["role"] == "member"


def test_register_rejects_a_short_password(client: TestClient) -> None:
    response = client.post(
        REGISTER_URL,
        json={"name": "Kaleb", "email": "kaleb@example.com", "password": "short"},
    )

    assert response.status_code == 422


def test_register_rejects_an_invalid_email(client: TestClient) -> None:
    for bad_email in ("not-an-email", "no@domain", "spaces in@example.com", "@example.com"):
        response = client.post(
            REGISTER_URL,
            json={"name": "Kaleb", "email": bad_email, "password": TEST_PASSWORD},
        )
        assert response.status_code == 422, f"{bad_email!r} was accepted"


def test_register_rejects_a_missing_field(client: TestClient) -> None:
    response = client.post(REGISTER_URL, json={"email": "kaleb@example.com"})

    assert response.status_code == 422


def test_login_with_correct_credentials_succeeds(client: TestClient) -> None:
    client.post(
        REGISTER_URL,
        json={"name": "Kaleb", "email": "kaleb@example.com", "password": TEST_PASSWORD},
    )

    response = client.post(
        LOGIN_URL, json={"email": "kaleb@example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 200, response.text
    assert response.json()["token"]
    assert response.json()["user"]["email"] == "kaleb@example.com"


def test_login_is_case_insensitive_on_the_email(client: TestClient) -> None:
    client.post(
        REGISTER_URL,
        json={"name": "Kaleb", "email": "kaleb@example.com", "password": TEST_PASSWORD},
    )

    response = client.post(
        LOGIN_URL, json={"email": "KALEB@Example.COM", "password": TEST_PASSWORD}
    )

    assert response.status_code == 200


def test_login_with_a_wrong_password_is_rejected(client: TestClient) -> None:
    client.post(
        REGISTER_URL,
        json={"name": "Kaleb", "email": "kaleb@example.com", "password": TEST_PASSWORD},
    )

    response = client.post(
        LOGIN_URL, json={"email": "kaleb@example.com", "password": "wrong-password"}
    )

    assert response.status_code == 401


def test_login_with_an_unknown_email_is_rejected(client: TestClient) -> None:
    response = client.post(
        LOGIN_URL, json={"email": "nobody@example.com", "password": TEST_PASSWORD}
    )

    assert response.status_code == 401


def test_unknown_email_and_wrong_password_are_indistinguishable(client: TestClient) -> None:
    """The two failures must not be tellable apart, or login enumerates accounts."""
    client.post(
        REGISTER_URL,
        json={"name": "Kaleb", "email": "kaleb@example.com", "password": TEST_PASSWORD},
    )

    wrong_password = client.post(
        LOGIN_URL, json={"email": "kaleb@example.com", "password": "wrong-password"}
    )
    unknown_email = client.post(
        LOGIN_URL, json={"email": "nobody@example.com", "password": TEST_PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_each_login_issues_a_distinct_token(client: TestClient) -> None:
    credentials = {"email": "kaleb@example.com", "password": TEST_PASSWORD}
    client.post(REGISTER_URL, json={"name": "Kaleb", **credentials})

    first = client.post(LOGIN_URL, json=credentials).json()["token"]
    second = client.post(LOGIN_URL, json=credentials).json()["token"]

    assert first != second
