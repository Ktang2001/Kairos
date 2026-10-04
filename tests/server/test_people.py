from fastapi.testclient import TestClient

from tests.server.conftest import auth_headers


def test_search_finds_user_by_partial_name(client: TestClient, make_user) -> None:
    make_user("Alice Anderson", "alice@example.com")
    make_user("Bob Brown", "bob@example.com")

    response = client.get("/people/search", params={"q": "ali"})

    assert response.status_code == 200
    results = response.json()
    assert len(results) == 1
    assert results[0]["name"] == "Alice Anderson"
    assert "password_hash" not in results[0]


def test_search_finds_user_by_partial_email(client: TestClient, make_user) -> None:
    make_user("Alice Anderson", "alice@example.com")

    response = client.get("/people/search", params={"q": "example.com"})

    assert response.status_code == 200
    assert len(response.json()) == 1


def test_blank_query_returns_no_results(client: TestClient, make_user) -> None:
    make_user("Alice Anderson", "alice@example.com")

    response = client.get("/people/search", params={"q": ""})

    assert response.status_code == 200
    assert response.json() == []


def test_get_person_by_id(client: TestClient, make_user) -> None:
    alice = make_user("Alice Anderson", "alice@example.com")

    response = client.get(f"/people/{alice.id}")

    assert response.status_code == 200
    assert response.json()["name"] == "Alice Anderson"


def test_get_person_404_for_unknown_id(client: TestClient) -> None:
    response = client.get("/people/999999")

    assert response.status_code == 404


def test_get_my_profile_includes_role(client: TestClient, make_user) -> None:
    alice = make_user("Alice Anderson", "alice@example.com", role_name="admin")

    response = client.get("/people/me", headers=auth_headers(alice.id))

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Alice Anderson"
    assert body["role"] == "admin"


def test_get_my_profile_requires_auth(client: TestClient) -> None:
    response = client.get("/people/me")

    assert response.status_code == 401


def test_me_route_is_not_swallowed_by_user_id_route(client: TestClient, make_user) -> None:
    """Regression check: /people/me must be registered before /people/{user_id}."""
    alice = make_user("Alice Anderson", "alice@example.com")

    response = client.get("/people/me", headers=auth_headers(alice.id))

    assert response.status_code == 200
    assert response.json()["id"] == alice.id
