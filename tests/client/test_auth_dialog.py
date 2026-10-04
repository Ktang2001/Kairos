import httpx

from client.views.auth_dialog import AuthDialog


class _FakeResponse:
    def __init__(self, status_code: int, json_body: dict) -> None:
        self.status_code = status_code
        self._json_body = json_body

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=self)

    def json(self) -> dict:
        return self._json_body


def _fake_post_dispatcher(responses: dict[str, _FakeResponse]):
    """Routes a mocked httpx.post by which endpoint suffix the url ends with -
    the dialog's two-step flow calls more than one endpoint per test."""

    def _post(url, json=None, timeout=5, verify=None):
        for suffix, response in responses.items():
            if url.endswith(suffix):
                return response
        raise AssertionError(f"unexpected POST to {url}")

    return _post


def test_login_success_enters_verify_step(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        _fake_post_dispatcher(
            {
                "/auth/login": _FakeResponse(
                    200, {"pending_token": "pend-1", "email": "alice@example.com"}
                )
            }
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.login_email.setText("alice@example.com")
    dialog.login_password.setText("hunter22")

    dialog._on_login()

    assert dialog.result() != AuthDialog.DialogCode.Accepted
    assert dialog._pages.currentIndex() == 1
    assert "alice@example.com" in dialog.verify_info_label.text()
    assert dialog._pending_token == "pend-1"


def test_login_wrong_password_shows_error(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx, "post", _fake_post_dispatcher({"/auth/login": _FakeResponse(401, {})})
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.login_email.setText("alice@example.com")
    dialog.login_password.setText("wrongpass")

    dialog._on_login()

    assert dialog.result() != AuthDialog.DialogCode.Accepted
    assert dialog._pages.currentIndex() == 0
    assert "Incorrect email or password" in dialog.login_status.text()


def test_signup_success_enters_verify_step(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        _fake_post_dispatcher(
            {
                "/auth/signup": _FakeResponse(
                    200, {"pending_token": "pend-2", "email": "bob@example.com"}
                )
            }
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.signup_name.setText("Bob")
    dialog.signup_email.setText("bob@example.com")
    dialog.signup_password.setText("hunter22")

    dialog._on_signup()

    assert dialog.result() != AuthDialog.DialogCode.Accepted
    assert dialog._pages.currentIndex() == 1
    assert dialog._pending_token == "pend-2"


def test_signup_duplicate_email_shows_error(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        _fake_post_dispatcher(
            {"/auth/signup": _FakeResponse(409, {"detail": "that email is already registered"})}
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.signup_name.setText("Bob")
    dialog.signup_email.setText("bob@example.com")
    dialog.signup_password.setText("hunter22")

    dialog._on_signup()

    assert dialog.result() != AuthDialog.DialogCode.Accepted
    assert "already registered" in dialog.signup_status.text()


def test_correct_code_accepts_dialog(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        _fake_post_dispatcher(
            {
                "/auth/login": _FakeResponse(
                    200, {"pending_token": "pend-1", "email": "alice@example.com"}
                ),
                "/auth/verify-code": _FakeResponse(
                    200,
                    {"id": 1, "name": "Alice", "email": "alice@example.com", "token": "tok-alice"},
                ),
            }
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.login_email.setText("alice@example.com")
    dialog.login_password.setText("hunter22")
    dialog._on_login()

    dialog.verify_code_input.setText("123456")
    dialog._on_verify_code()

    assert dialog.result() == AuthDialog.DialogCode.Accepted
    assert dialog.result_user_id == 1
    assert dialog.result_user_name == "Alice"
    assert dialog.result_token == "tok-alice"


def test_wrong_code_shows_error_and_stays_on_verify_page(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        _fake_post_dispatcher(
            {
                "/auth/login": _FakeResponse(
                    200, {"pending_token": "pend-1", "email": "alice@example.com"}
                ),
                "/auth/verify-code": _FakeResponse(401, {}),
            }
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.login_email.setText("alice@example.com")
    dialog.login_password.setText("hunter22")
    dialog._on_login()

    dialog.verify_code_input.setText("000000")
    dialog._on_verify_code()

    assert dialog.result() != AuthDialog.DialogCode.Accepted
    assert dialog._pages.currentIndex() == 1
    assert "Incorrect or expired code" in dialog.verify_status.text()


def test_resend_code_shows_confirmation(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        _fake_post_dispatcher(
            {
                "/auth/signup": _FakeResponse(
                    200, {"pending_token": "pend-2", "email": "bob@example.com"}
                ),
                "/auth/resend-code": _FakeResponse(
                    200, {"pending_token": "pend-2", "email": "bob@example.com"}
                ),
            }
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.signup_name.setText("Bob")
    dialog.signup_email.setText("bob@example.com")
    dialog.signup_password.setText("hunter22")
    dialog._on_signup()

    dialog._on_resend_code()

    assert "new code has been sent" in dialog.verify_status.text()
