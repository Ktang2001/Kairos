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


def test_login_success_accepts_dialog(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, json=None, timeout=5: _FakeResponse(
            200, {"id": 1, "name": "Alice", "email": "alice@example.com"}
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.login_email.setText("alice@example.com")
    dialog.login_password.setText("hunter22")

    dialog._on_login()

    assert dialog.result() == AuthDialog.DialogCode.Accepted
    assert dialog.result_user_id == 1
    assert dialog.result_user_name == "Alice"


def test_login_wrong_password_shows_error(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=5: _FakeResponse(401, {}))

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.login_email.setText("alice@example.com")
    dialog.login_password.setText("wrongpass")

    dialog._on_login()

    assert dialog.result() != AuthDialog.DialogCode.Accepted
    assert "Incorrect email or password" in dialog.login_status.text()


def test_signup_success_accepts_dialog(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, json=None, timeout=5: _FakeResponse(
            200, {"id": 2, "name": "Bob", "email": "bob@example.com"}
        ),
    )

    dialog = AuthDialog(base_url="http://localhost:8000")
    qtbot.addWidget(dialog)
    dialog.signup_name.setText("Bob")
    dialog.signup_email.setText("bob@example.com")
    dialog.signup_password.setText("hunter22")

    dialog._on_signup()

    assert dialog.result() == AuthDialog.DialogCode.Accepted
    assert dialog.result_user_id == 2
    assert dialog.result_user_name == "Bob"


def test_signup_duplicate_email_shows_error(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "post",
        lambda url, json=None, timeout=5: _FakeResponse(
            409, {"detail": "that email is already registered"}
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
