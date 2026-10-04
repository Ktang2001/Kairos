from fastapi.testclient import TestClient

from server.models.session import Session
from server.models.user import User
from server.services import verification_service
from tests.server.conftest import auth_headers


def _code_for(sent_codes: list[tuple[str, str]], email: str) -> str:
    """The most recent code sent to `email` - helper for tests that only care
    about one user's code at a time."""
    for sent_email, code in reversed(sent_codes):
        if sent_email == email:
            return code
    raise AssertionError(f"no code was sent to {email}")


def _signup_and_verify(
    client: TestClient, sent_codes: list[tuple[str, str]], name, email, password
) -> dict:
    """Full two-step flow: signup -> grab the mocked "sent" code -> verify it.
    Returns the final AuthResult body (id, name, email, token)."""
    pending = client.post(
        "/auth/signup", json={"name": name, "email": email, "password": password}
    ).json()
    code = _code_for(sent_codes, email)
    verified = client.post(
        "/auth/verify-code", json={"pending_token": pending["pending_token"], "code": code}
    )
    assert verified.status_code == 200
    return verified.json()


def _login_and_verify(
    client: TestClient, sent_codes: list[tuple[str, str]], email, password
) -> dict:
    pending = client.post("/auth/login", json={"email": email, "password": password}).json()
    code = _code_for(sent_codes, email)
    verified = client.post(
        "/auth/verify-code", json={"pending_token": pending["pending_token"], "code": code}
    )
    assert verified.status_code == 200
    return verified.json()


def test_signup_sends_a_code_and_withholds_the_session(client: TestClient, sent_codes) -> None:
    response = client.post(
        "/auth/signup",
        json={"name": "Alice Anderson", "email": "alice@example.com", "password": "hunter22"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "token" not in body
    assert sent_codes == [("alice@example.com", sent_codes[0][1])]
    assert len(sent_codes[0][1]) == 6


def test_signup_creates_member_user_only_after_code_verified(
    client: TestClient, db_session, sent_codes
) -> None:
    result = _signup_and_verify(
        client, sent_codes, "Alice Anderson", "alice@example.com", "hunter22"
    )

    assert result["name"] == "Alice Anderson"
    assert "password" not in result
    assert "password_hash" not in result
    assert result["token"]

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


def test_login_succeeds_with_correct_password_after_code_verified(
    client: TestClient, sent_codes
) -> None:
    _signup_and_verify(client, sent_codes, "Alice Anderson", "alice@example.com", "hunter22")
    # A real user wouldn't log in seconds after signing up (they'd use the
    # session signup already gave them) - clear the resend cooldown so this
    # test's back-to-back signup+login isn't mistaken for the same thing.
    verification_service._last_sent_at.clear()

    result = _login_and_verify(client, sent_codes, "alice@example.com", "hunter22")

    assert result["name"] == "Alice Anderson"
    assert result["token"]


def test_login_fails_with_wrong_password(client: TestClient, sent_codes) -> None:
    _signup_and_verify(client, sent_codes, "Alice", "alice@example.com", "hunter22")

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrongpass"}
    )

    assert response.status_code == 401


def test_login_fails_for_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )

    assert response.status_code == 401


def test_login_issues_a_usable_session_token(client: TestClient, db_session, sent_codes) -> None:
    _signup_and_verify(client, sent_codes, "Alice Anderson", "alice@example.com", "hunter22")
    verification_service._last_sent_at.clear()

    result = _login_and_verify(client, sent_codes, "alice@example.com", "hunter22")
    token = result["token"]
    assert db_session.get(Session, token) is not None

    protected = client.get("/people/me", headers=auth_headers(token))
    assert protected.status_code == 200
    assert protected.json()["email"] == "alice@example.com"


def test_verify_code_rejects_wrong_code(client: TestClient, sent_codes) -> None:
    pending = client.post(
        "/auth/signup",
        json={"name": "Alice", "email": "alice@example.com", "password": "hunter22"},
    ).json()

    response = client.post(
        "/auth/verify-code",
        json={"pending_token": pending["pending_token"], "code": "000000"},
    )

    assert response.status_code == 401


def test_verify_code_rejects_unknown_pending_token(client: TestClient) -> None:
    response = client.post(
        "/auth/verify-code", json={"pending_token": "not-a-real-token", "code": "123456"}
    )

    assert response.status_code == 401


def test_login_right_after_signup_hits_cooldown_cleanly(client: TestClient, sent_codes) -> None:
    """Regression test: a login attempt within the resend cooldown window of a
    prior signup/login must 429, not raise an unhandled 500 (ResendCooldownError
    needs to be caught in _start_verification too, not just /auth/resend-code)."""
    client.post(
        "/auth/signup",
        json={"name": "Alice", "email": "alice@example.com", "password": "hunter22"},
    )

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )

    assert response.status_code == 429


def test_resend_code_rejects_rapid_repeat(client: TestClient, sent_codes) -> None:
    pending = client.post(
        "/auth/signup",
        json={"name": "Alice", "email": "alice@example.com", "password": "hunter22"},
    ).json()

    resend = client.post("/auth/resend-code", json={"pending_token": pending["pending_token"]})
    assert resend.status_code == 429  # cooldown - just requested one moment ago


def test_resend_code_issues_a_new_code(client: TestClient, sent_codes) -> None:
    pending = client.post(
        "/auth/signup",
        json={"name": "Alice", "email": "alice@example.com", "password": "hunter22"},
    ).json()
    first_code = _code_for(sent_codes, "alice@example.com")
    verification_service._last_sent_at.clear()  # bypass the cooldown tested above

    resend = client.post("/auth/resend-code", json={"pending_token": pending["pending_token"]})
    assert resend.status_code == 200
    second_code = _code_for(sent_codes, "alice@example.com")
    assert second_code != first_code

    stale = client.post(
        "/auth/verify-code",
        json={"pending_token": pending["pending_token"], "code": first_code},
    )
    assert stale.status_code == 401

    fresh = client.post(
        "/auth/verify-code",
        json={"pending_token": pending["pending_token"], "code": second_code},
    )
    assert fresh.status_code == 200


def test_logout_invalidates_the_token(client: TestClient, sent_codes) -> None:
    signup = _signup_and_verify(client, sent_codes, "Alice", "alice@example.com", "hunter22")
    token = signup["token"]

    logout_response = client.post("/auth/logout", headers=auth_headers(token))
    assert logout_response.status_code == 204

    reused = client.get("/people/me", headers=auth_headers(token))
    assert reused.status_code == 401


def test_repeated_failed_logins_trigger_a_cooldown(client: TestClient, sent_codes) -> None:
    _signup_and_verify(client, sent_codes, "Alice", "alice@example.com", "hunter22")

    for _ in range(5):
        response = client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "wrong-pw"}
        )
        assert response.status_code == 401

    cooldown_response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )
    assert cooldown_response.status_code == 429
