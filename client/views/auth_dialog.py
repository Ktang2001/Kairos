import httpx
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class AuthDialog(QDialog):
    """Sign up for a new Kairos account or log in to an existing one.

    This is real credential-backed identification (password hashed + verified
    server-side - see server/services/auth_service.py). Per-request authorization
    elsewhere still relies on the placeholder X-Kairos-User-Id header (see
    server/api/dependencies.py) until real sessions/tokens replace it.
    """

    def __init__(self, base_url: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Sign in to Kairos")
        self._base_url = base_url

        self.result_user_id: int | None = None
        self.result_user_name: str | None = None

        tabs = QTabWidget()
        tabs.addTab(self._build_login_tab(), "Log In")
        tabs.addTab(self._build_signup_tab(), "Sign Up")

        layout = QVBoxLayout()
        layout.addWidget(tabs)
        self.setLayout(layout)

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
        self.signup_status = QLabel("")

        form = QFormLayout()
        form.addRow("Name:", self.signup_name)
        form.addRow("Email:", self.signup_email)
        form.addRow("Password:", self.signup_password)

        button = QPushButton("Sign Up")
        button.clicked.connect(self._on_signup)

        layout = QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(button)
        layout.addWidget(self.signup_status)

        tab = QWidget()
        tab.setLayout(layout)
        return tab

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
            )
        except httpx.HTTPError as exc:
            self.login_status.setText(f"Could not reach server: {exc}")
            return

        if response.status_code == 401:
            self.login_status.setText("Incorrect email or password.")
            return
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            self.login_status.setText(f"Login failed: {exc}")
            return

        person = response.json()
        self.result_user_id = person["id"]
        self.result_user_name = person["name"]
        self.accept()

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
                json={"name": name, "email": email, "password": password},
                timeout=5,
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

        person = response.json()
        self.result_user_id = person["id"]
        self.result_user_name = person["name"]
        self.accept()
