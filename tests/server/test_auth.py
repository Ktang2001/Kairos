from fastapi.testclient import TestClient

from server import email_sender
from server.models.session import Session
from server.models.user import User
from server.services import verification_service
from tests.server.conftest import auth_headers


def _signup(
    client: TestClient, name: str, email: str, password: str, two_factor_enabled: bool = False
) -> dict:
    """Signup has no 2FA step itself - it's a real session immediately, whatever
    `two_factor_enabled` is chosen (that only affects future logins)."""
    response = client.post(
        "/auth/signup",
        json={
            "name": name,
            "email": email,
            "password": password,
            "two_factor_enabled": two_factor_enabled,
        },
    )
    assert response.status_code == 200
    return response.json()


def _code_for(sent_codes: list[tuple[str, str]], email: str) -> str:
    """The most recent code sent to `email` - helper for tests that only care
    about one user's code at a time."""
    for sent_email, code in reversed(sent_codes):
        if sent_email == email:
            return code
    raise AssertionError(f"no code was sent to {email}")


def _login_and_verify(
    client: TestClient, sent_codes: list[tuple[str, str]], email, password
) -> dict:
    """A 2FA-enabled account's login flow: password check -> grab the mocked
    "sent" code -> verify it. Returns the final AuthResult body."""
    pending = client.post("/auth/login", json={"email": email, "password": password}).json()
    code = _code_for(sent_codes, email)
    verified = client.post(
        "/auth/verify-code", json={"pending_token": pending["pending_token"], "code": code}
    )
    assert verified.status_code == 200
    return verified.json()


# --- Signup: no 2FA, but the 2FA-on-login choice is saved ---


def test_signup_issues_a_session_immediately(client: TestClient, db_session, sent_codes) -> None:
    result = _signup(client, "Alice Anderson", "alice@example.com", "hunter22")

    assert result["name"] == "Alice Anderson"
    assert "password" not in result
    assert "password_hash" not in result
    assert result["token"]
    assert sent_codes == []  # no email involved in signup at all

    user = db_session.query(User).filter_by(email="alice@example.com").first()
    assert user is not None
    assert user.role.name == "member"
    assert user.password_hash != "hunter22"  # actually hashed, not stored raw


def test_signup_defaults_to_2fa_disabled(client: TestClient, db_session) -> None:
    _signup(client, "Alice", "alice@example.com", "hunter22")

    user = db_session.query(User).filter_by(email="alice@example.com").first()
    assert user.two_factor_enabled is False


def test_signup_can_opt_into_2fa(client: TestClient, db_session) -> None:
    _signup(client, "Alice", "alice@example.com", "hunter22", two_factor_enabled=True)

    user = db_session.query(User).filter_by(email="alice@example.com").first()
    assert user.two_factor_enabled is True


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


def test_signup_issued_token_works_immediately(client: TestClient) -> None:
    result = _signup(client, "Alice", "alice@example.com", "hunter22")

    protected = client.get("/people/me", headers=auth_headers(result["token"]))
    assert protected.status_code == 200
    assert protected.json()["email"] == "alice@example.com"


# --- Login: no 2FA by default ---


def test_login_without_2fa_issues_a_session_immediately(client: TestClient, sent_codes) -> None:
    _signup(client, "Alice Anderson", "alice@example.com", "hunter22")  # 2FA off by default

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["token"]
    assert "pending_token" not in body
    assert sent_codes == []  # no code sent - this account never opted in


def test_login_fails_with_wrong_password(client: TestClient) -> None:
    _signup(client, "Alice", "alice@example.com", "hunter22")

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "wrongpass"}
    )

    assert response.status_code == 401


def test_login_fails_for_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )

    assert response.status_code == 401


def test_repeated_failed_logins_trigger_a_cooldown(client: TestClient) -> None:
    _signup(client, "Alice", "alice@example.com", "hunter22")

    for _ in range(5):
        response = client.post(
            "/auth/login", json={"email": "alice@example.com", "password": "wrong-pw"}
        )
        assert response.status_code == 401

    cooldown_response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )
    assert cooldown_response.status_code == 429


def test_logout_invalidates_the_token(client: TestClient) -> None:
    signup = _signup(client, "Alice", "alice@example.com", "hunter22")
    token = signup["token"]

    logout_response = client.post("/auth/logout", headers=auth_headers(token))
    assert logout_response.status_code == 204

    reused = client.get("/people/me", headers=auth_headers(token))
    assert reused.status_code == 401


# --- Login: 2FA, for accounts that opted in at signup ---


def test_login_with_2fa_sends_a_code_and_withholds_the_session(
    client: TestClient, sent_codes
) -> None:
    _signup(client, "Alice Anderson", "alice@example.com", "hunter22", two_factor_enabled=True)

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "alice@example.com"
    assert "token" not in body
    assert sent_codes == [("alice@example.com", sent_codes[0][1])]
    assert len(sent_codes[0][1]) == 6


def test_login_with_2fa_succeeds_after_code_verified(client: TestClient, sent_codes) -> None:
    _signup(client, "Alice Anderson", "alice@example.com", "hunter22", two_factor_enabled=True)

    result = _login_and_verify(client, sent_codes, "alice@example.com", "hunter22")

    assert result["name"] == "Alice Anderson"
    assert result["token"]


def test_login_with_2fa_issues_a_usable_session_token(
    client: TestClient, db_session, sent_codes
) -> None:
    _signup(client, "Alice Anderson", "alice@example.com", "hunter22", two_factor_enabled=True)

    result = _login_and_verify(client, sent_codes, "alice@example.com", "hunter22")
    token = result["token"]
    assert db_session.get(Session, token) is not None

    protected = client.get("/people/me", headers=auth_headers(token))
    assert protected.status_code == 200
    assert protected.json()["email"] == "alice@example.com"


def test_login_with_2fa_right_after_login_hits_resend_cooldown_cleanly(
    client: TestClient, sent_codes
) -> None:
    """Regression test: a second login attempt within the resend cooldown window
    of a first one must 429, not raise an unhandled 500 (ResendCooldownError
    needs to be caught in _start_verification)."""
    _signup(client, "Alice", "alice@example.com", "hunter22", two_factor_enabled=True)
    client.post("/auth/login", json={"email": "alice@example.com", "password": "hunter22"})

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )

    assert response.status_code == 429


def test_login_with_2fa_returns_a_clean_503_when_email_sending_fails(
    client: TestClient, sent_codes, monkeypatch
) -> None:
    """Regression test: if SMTP isn't configured (or fails for any reason), this
    must 503 with a clear message, not crash with an unhandled 500 (reproduces
    what happened when KAIROS_SMTP_USER/PASSWORD weren't set on a real run)."""
    _signup(client, "Alice", "alice@example.com", "hunter22", two_factor_enabled=True)

    def _raise(to_email, code):
        raise RuntimeError("KAIROS_SMTP_USER and KAIROS_SMTP_PASSWORD must be set")

    monkeypatch.setattr(email_sender, "send_verification_code", _raise)

    response = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    )

    assert response.status_code == 503
    assert "KAIROS_SMTP_USER" in response.json()["detail"]


def test_verify_code_rejects_wrong_code(client: TestClient, sent_codes) -> None:
    _signup(client, "Alice", "alice@example.com", "hunter22", two_factor_enabled=True)
    pending = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
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


def test_resend_code_rejects_rapid_repeat(client: TestClient, sent_codes) -> None:
    _signup(client, "Alice", "alice@example.com", "hunter22", two_factor_enabled=True)
    pending = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
    ).json()

    resend = client.post("/auth/resend-code", json={"pending_token": pending["pending_token"]})
    assert resend.status_code == 429  # cooldown - just requested one moment ago


def test_resend_code_issues_a_new_code(client: TestClient, sent_codes) -> None:
    _signup(client, "Alice", "alice@example.com", "hunter22", two_factor_enabled=True)
    pending = client.post(
        "/auth/login", json={"email": "alice@example.com", "password": "hunter22"}
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
