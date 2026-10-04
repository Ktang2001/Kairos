from fastapi.testclient import TestClient

from server.models.user import User


def test_signup_creates_member_user(client: TestClient, db_session) -> None:
    response = client.post(
        "/auth/signup",
        json={"name": "Alice Anderson", "email": "alice@example.com", "password": "hunter22"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Alice Anderson"
    assert "password" not in body
    assert "password_hash" not in body

    user = db_session.query(User).filter_by(email="alice@example.com").first()
    assert user is not None
    assert user.role.name == "member"
    assert user.password_hash != "hunter22"  # actually hashed, not stored raw


def test_signup_rejects_duplicate_email(client: TestClient) -> None:
    client.post(
        "/auth/signup",
        json={"name": "Alice", "email": "alice@example.com", "password": "hunter22"},
    )

    response = client.post(
        "/auth/signup",
        json={"name": "Someone Else", "email": "alice@example.com", "password": "another1"},
    )

    assert response.status_code == 409


def test_signup_rejects_short_password(client: TestClient) -> None:
    response = client.post(
        "/auth/signup", json={"name": "Alice", "email": "alice@example.com", "password": "short"}
    )

    assert response.status_code == 400


def test_login_succeeds_with_correct_password(client: TestClient) -> None:
    client.post(
        "/auth/signup",
        json={"name": "Alice Anderson", "email": "alice@example.com", "password": "hunter22"},
    )

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Alice Anderson"


def test_login_fails_with_wrong_password(client: TestClient) -> None:
    client.post(
        "/auth/signup",
        json={"name": "Alice", "email": "alice@example.com", "password": "hunter22"},
    )

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrongpass"}
    )

    assert response.status_code == 401


def test_login_fails_for_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )

    assert response.status_code == 401
