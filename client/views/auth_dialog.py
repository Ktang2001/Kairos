import httpx
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from client.net.cert_pinning import build_pinned_ssl_context


class AuthDialog(QDialog):
    """Sign up for a new Kairos account or log in to an existing one.

    Real credential-backed identification (password hashed + verified server-side -
    see server/services/auth_service.py). Signup always issues a session
    immediately - it never does 2FA itself - but has a checkbox letting the
    signer-upper opt in to requiring an emailed 6-digit code
    (server/services/verification_service.py) on future logins
    (User.two_factor_enabled). Login then branches on that per-account choice:
    opted-in accounts get a `pending_token` and must complete the verify-code
    step; everyone else gets a session immediately, same as signup. Either way,
    the final session token (see server/services/session_service.py) is what
    every subsequent request must carry as `Authorization: Bearer <token>`
    (see server/api/dependencies.py).
    """

    def __init__(
        self, base_url: str, cert_pem: str | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in to Kairos")
        self._base_url = base_url
        # Same pinned-certificate trust as ApiClient (see client/net/cert_pinning.py) -
        # this dialog makes its own requests rather than going through ApiClient,
        # since no token exists yet at signup/login time.
        self._verify = build_pinned_ssl_context(cert_pem) if cert_pem else True
        self._pending_token: str | None = None

        self.result_user_id: int | None = None
        self.result_user_name: str | None = None
        self.result_token: str | None = None

        self._pages = QStackedWidget()
        self._pages.addWidget(self._build_credentials_page())
        self._pages.addWidget(self._build_verify_page())

        layout = QVBoxLayout()
        layout.addWidget(self._pages)
        self.setLayout(layout)

    def _build_credentials_page(self) -> QWidget:
        tabs = QTabWidget()
        tabs.addTab(self._build_login_tab(), "Log In")
        tabs.addTab(self._build_signup_tab(), "Sign Up")

        page = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(tabs)
        page.setLayout(layout)
        return page

    def _build_verify_page(self) -> QWidget:
        self.verify_info_label = QLabel("")
        self.verify_info_label.setWordWrap(True)
        self.verify_code_input = QLineEdit()
        self.verify_status = QLabel("")

        form = QFormLayout()
        form.addRow("Code:", self.verify_code_input)

        verify_button = QPushButton("Verify")
        verify_button.clicked.connect(self._on_verify_code)
        resend_button = QPushButton("Resend code")
        resend_button.clicked.connect(self._on_resend_code)

        button_row = QHBoxLayout()
        button_row.addWidget(verify_button)
        button_row.addWidget(resend_button)

        layout = QVBoxLayout()
        layout.addWidget(self.verify_info_label)
        layout.addLayout(form)
        layout.addLayout(button_row)
        layout.addWidget(self.verify_status)

        page = QWidget()
        page.setLayout(layout)
        return page

    def _build_login_tab(self) -> QWidget:
        self.login_email = QLineEdit()
        self.login_password = QLineEdit()
        self.login_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.login_status = QLabel("")

        form = QFormLayout()
        form.addRow("Email:", self.login_email)
        form.addRow("Password:", self.login_password)

        button = QPushButton("Log In")
        button.clicked.connect(self._on_login)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(button)
        layout.addWidget(self.login_status)

        tab = QWidget()
        tab.setLayout(layout)
        return tab

    def _build_signup_tab(self) -> QWidget:
        self.signup_name = QLineEdit()
        self.signup_email = QLineEdit()
        self.signup_password = QLineEdit()
        self.signup_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.signup_2fa_checkbox = QCheckBox("Require an emailed code when logging in (2FA)")
        self.signup_status = QLabel("")

        form = QFormLayout()
        form.addRow("Name:", self.signup_name)
        form.addRow("Email:", self.signup_email)
        form.addRow("Password:", self.signup_password)

        button = QPushButton("Sign Up")
        button.clicked.connect(self._on_signup)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(self.signup_2fa_checkbox)
        layout.addWidget(button)
        layout.addWidget(self.signup_status)

        tab = QWidget()
        tab.setLayout(layout)
        return tab

    def _enter_verify_step(self, email: str, pending_token: str) -> None:
        self._pending_token = pending_token
        self.verify_info_label.setText(f"We've emailed a 6-digit code to {email}.")
        self.verify_code_input.clear()
        self.verify_status.setText("")
        self._pages.setCurrentIndex(1)

    def _accept_with_auth_result(self, person: dict) -> None:
        self.result_user_id = person["id"]
        self.result_user_name = person["name"]
        self.result_token = person["token"]
        self.accept()

    def _on_login(self) -> None:
        email = self.login_email.text().strip()
        password = self.login_password.text()
        if not email or not password:
            self.login_status.setText("Email and password are required.")
            return

        try:
            response = httpx.post(
                f"{self._base_url}/auth/login",
                json={"email": email, "password": password},
                timeout=5,
                verify=self._verify,
            )
        except httpx.HTTPError as exc:
            self.login_status.setText(f"Could not reach server: {exc}")
            return

        if response.status_code == 401:
            self.login_status.setText("Incorrect email or password.")
            return
        if response.status_code in (429, 503):
            self.login_status.setText(response.json().get("detail", "Could not log in."))
            return
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self.login_status.setText(f"Login failed: {exc}")
            return

        body = response.json()
        self.login_status.setText("")
        if "token" in body:
            # This account didn't opt into 2FA at signup - a session comes back
            # immediately, same as signup always does (see server/api/auth.py).
            self._accept_with_auth_result(body)
        else:
            self._enter_verify_step(body["email"], body["pending_token"])

    def _on_signup(self) -> None:
        name = self.signup_name.text().strip()
        email = self.signup_email.text().strip()
        password = self.signup_password.text()
        if not name or not email or not password:
            self.signup_status.setText("Name, email, and password are required.")
            return

        try:
            response = httpx.post(
                f"{self._base_url}/auth/signup",
                json={
                    "name": name,
                    "email": email,
                    "password": password,
                    "two_factor_enabled": self.signup_2fa_checkbox.isChecked(),
                },
                timeout=5,
                verify=self._verify,
            )
        except httpx.HTTPError as exc:
            self.signup_status.setText(f"Could not reach server: {exc}")
            return

        if response.status_code in (400, 409):
            self.signup_status.setText(response.json().get("detail", "Could not sign up."))
            return
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self.signup_status.setText(f"Signup failed: {exc}")
            return

        # No 2FA step for signup itself (see server/api/auth.py) - the session is
        # ready immediately, whatever the chosen 2FA-on-login preference above.
        self._accept_with_auth_result(response.json())

    def _on_verify_code(self) -> None:
        code = self.verify_code_input.text().strip()
        if not code:
            self.verify_status.setText("Enter the code.")
            return

        try:
            response = httpx.post(
                f"{self._base_url}/auth/verify-code",
                json={"pending_token": self._pending_token, "code": code},
                timeout=5,
                verify=self._verify,
            )
        except httpx.HTTPError as exc:
            self.verify_status.setText(f"Could not reach server: {exc}")
            return

        if response.status_code == 401:
            self.verify_status.setText("Incorrect or expired code.")
            return
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self.verify_status.setText(f"Verification failed: {exc}")
            return

        self._accept_with_auth_result(response.json())

    def _on_resend_code(self) -> None:
        try:
            response = httpx.post(
                f"{self._base_url}/auth/resend-code",
                json={"pending_token": self._pending_token},
                timeout=5,
                verify=self._verify,
            )
        except httpx.HTTPError as exc:
            self.verify_status.setText(f"Could not reach server: {exc}")
            return

        if response.status_code in (429, 503):
            self.verify_status.setText(
                response.json().get("detail", "Please wait before retrying.")
            )
            return
        if response.status_code == 404:
            self.verify_status.setText(
                "This verification attempt has expired - go back and try again."
            )
            return
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self.verify_status.setText(f"Could not resend code: {exc}")
            return

        self.verify_status.setText("A new code has been sent.")
