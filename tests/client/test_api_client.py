"""Tests for client.api_client against the real API (the ``live_server`` fixture)."""

import httpx
import pytest

from client.api_client import ApiClient, ApiError, normalise_base_url
from tests.client.conftest import TEST_PASSWORD, unique_email

# ---------------------------------------------------------- server addresses


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("http://localhost:8000", "http://127.0.0.1:8000"),
        ("localhost:8000", "http://127.0.0.1:8000"),
        ("192.168.1.5:8000", "http://192.168.1.5:8000"),
        ("  http://192.168.1.5:8000/  ", "http://192.168.1.5:8000"),
        ("http://host:8000//", "http://host:8000"),
        ("https://kairos.example.com", "https://kairos.example.com"),
    ],
)
def test_server_addresses_are_normalised(typed: str, expected: str) -> None:
    assert normalise_base_url(typed) == expected


@pytest.mark.parametrize("typed", ["", "   ", "not a url", "ftp://host:21", "http://", "http:// x"])
def test_invalid_server_addresses_are_rejected(typed: str) -> None:
    with pytest.raises(ApiError) as caught:
        normalise_base_url(typed)
    assert caught.value.status_code is None
    assert caught.value.message


# ------------------------------------------------------------ happy path


def test_register_signs_in_and_me_returns_the_user(live_server: str) -> None:
    email = unique_email()
    client = ApiClient(live_server)

    user = client.register("Nick", email, TEST_PASSWORD)

    assert client.token
    assert user["email"] == email
    assert user["role"] == "member"
    assert client.me()["id"] == user["id"]


def test_login_stores_the_token(live_server: str) -> None:
    email = unique_email()
    ApiClient(live_server).register("Nick", email, TEST_PASSWORD)

    client = ApiClient(live_server)
    assert client.token is None
    client.login(email, TEST_PASSWORD)
    assert client.token
    assert client.me()["email"] == email


def test_logout_revokes_the_token_on_the_server(live_server: str) -> None:
    client = ApiClient(live_server)
    client.register("Nick", unique_email(), TEST_PASSWORD)
    token = client.token

    client.logout()

    assert client.token is None
    response = httpx.get(f"{live_server}/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


def test_logout_without_a_session_does_nothing(live_server: str) -> None:
    client = ApiClient(live_server)
    client.logout()
    assert client.token is None


# ------------------------------------------------------------- failures


def test_a_wrong_password_raises_the_servers_message(live_server: str) -> None:
    email = unique_email()
    ApiClient(live_server).register("Nick", email, TEST_PASSWORD)

    client = ApiClient(live_server)
    with pytest.raises(ApiError) as caught:
        client.login(email, "wrong-password")

    assert caught.value.status_code == 401
    assert caught.value.message == "Incorrect email or password"
    assert client.token is None


def test_a_duplicate_email_raises_409(live_server: str) -> None:
    email = unique_email()
    ApiClient(live_server).register("Nick", email, TEST_PASSWORD)

    with pytest.raises(ApiError) as caught:
        ApiClient(live_server).register("Other", email, TEST_PASSWORD)
    assert caught.value.status_code == 409
    assert "already registered" in caught.value.message


def test_validation_errors_are_turned_into_a_sentence(live_server: str) -> None:
    """A 422 body is a list of dicts; the user should see one readable line."""
    with pytest.raises(ApiError) as caught:
        ApiClient(live_server).register("Nick", unique_email(), "short")
    assert caught.value.status_code == 422
    assert caught.value.message.startswith("Password: ")
    assert "8" in caught.value.message


def test_an_unreachable_host_gives_a_clear_message(dead_server: str) -> None:
    with pytest.raises(ApiError) as caught:
        ApiClient(dead_server).login("a@example.com", "whatever")
    assert caught.value.status_code is None
    assert "Can't reach the server" in caught.value.message
    assert dead_server in caught.value.message


def test_a_hung_host_times_out_with_a_clear_message(silent_server: str) -> None:
    with pytest.raises(ApiError) as caught:
        ApiClient(silent_server, timeout=0.3).login("a@example.com", "whatever")
    assert caught.value.status_code is None
    assert "took too long" in caught.value.message


def test_logout_never_raises_even_if_the_host_is_gone(live_server: str, dead_server: str) -> None:
    client = ApiClient(live_server)
    client.register("Nick", unique_email(), TEST_PASSWORD)
    client.base_url = dead_server  # the host goes away mid-session

    client.logout()

    assert client.token is None


def test_an_expired_or_revoked_token_raises_401(live_server: str) -> None:
    client = ApiClient(live_server)
    client.register("Nick", unique_email(), TEST_PASSWORD)
    client.token = "not-a-real-token"
    with pytest.raises(ApiError) as caught:
        client.me()
    assert caught.value.status_code == 401
