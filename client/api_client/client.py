import os
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"

#: Seconds to wait for the host. Long enough for a slow LAN, short enough that
#: "the host is off" is reported promptly instead of looking like a hang.
DEFAULT_TIMEOUT = 5.0


class ApiError(Exception):
    """Any failed call, carrying a message fit to show the user as-is.

    ``status_code`` is the HTTP status when the server answered, or ``None``
    when it could not be reached at all.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def normalise_base_url(text: str) -> str:
    """Turn what a person typed into a usable base URL, or raise ApiError.

    Accepts ``192.168.1.5:8000`` as well as ``http://192.168.1.5:8000/``:
    adds a missing ``http://`` and drops trailing slashes, so typing the
    address the server window shows "just works".
    """
    candidate = text.strip()
    if not candidate:
        raise ApiError("Enter the server address.")
    if "://" not in candidate:
        candidate = f"http://{candidate}"
    # Strip slashes only after the scheme: stripping first would turn
    # "http://" into "http:", which then gained a scheme and a host of "http".
    scheme, separator, rest = candidate.partition("://")
    candidate = f"{scheme}{separator}{rest.rstrip('/')}"

    try:
        url = httpx.URL(candidate)
    except httpx.InvalidURL:
        url = None
    if url is None or url.scheme not in ("http", "https") or not url.host or " " in candidate:
        raise ApiError(f"{text.strip()!r} is not a valid server address.")
    return candidate


def _error_message(response: httpx.Response) -> str:
    """Pull a human-readable message out of an error response.

    The server answers either ``{"detail": "..."}`` or, for a body that failed
    validation, ``{"detail": [{"loc": [..., "password"], "msg": "..."}]}``.
    """
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        detail = None

    if isinstance(detail, str):
        return detail
    if isinstance(detail, list) and detail and isinstance(detail[0], dict):
        first = detail[0]
        field = str(first.get("loc", ["", ""])[-1]).replace("_", " ").capitalize()
        message = str(first.get("msg", "is invalid"))
        message = message.removeprefix("Value error, ")
        return f"{field}: {message}" if field else message
    return f"The server returned an error ({response.status_code})."


class ApiClient:
    """Thin wrapper around the Kairos REST backend.

    Host address is configurable via the KAIROS_SERVER_URL env var (or
    the constructor arg) rather than hardcoded, since either teammate's
    machine may be hosting the backend for a given session.

    After ``login`` or ``register`` the session token is held in memory and
    sent with every request. It is never written to disk.

    Every failure -- unreachable host, timeout, or an error response -- is
    raised as ``ApiError`` with a message ready to display.
    """

    def __init__(self, base_url: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = normalise_base_url(
            base_url or os.environ.get("KAIROS_SERVER_URL", DEFAULT_BASE_URL)
        )
        self.timeout = timeout
        self.token: str | None = None

    def _request(self, method: str, path: str, *, json: dict | None = None) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            raise ApiError(f"The server at {self.base_url} took too long to answer.") from None
        except httpx.TransportError:
            raise ApiError(
                f"Can't reach the server at {self.base_url}. "
                "Is it running, and is the address right?"
            ) from None

        if response.is_success:
            return response.json() if response.content else None
        raise ApiError(_error_message(response), response.status_code)

    def health(self) -> dict:
        return self._request("GET", "/health")

    def login(self, email: str, password: str) -> dict:
        """Sign in; keeps the token and returns the user (id, name, email, role)."""
        body = self._request("POST", "/auth/login", json={"email": email, "password": password})
        self.token = body["token"]
        return body["user"]

    def register(self, name: str, email: str, password: str) -> dict:
        """Create an account, which also signs it in. Returns the user."""
        body = self._request(
            "POST",
            "/auth/register",
            json={"name": name, "email": email, "password": password},
        )
        self.token = body["token"]
        return body["user"]

    def logout(self) -> None:
        """Revoke the session on the server and forget the token.

        Never raises: signing out must work even when the host has gone away.
        The token is forgotten locally either way; if the server could not be
        told, the session simply expires on its own.
        """
        if self.token is None:
            return
        try:
            self._request("POST", "/auth/logout")
        except ApiError:
            pass
        finally:
            self.token = None

    def me(self) -> dict:
        return self._request("GET", "/auth/me")

    def send_message(self, content: str) -> dict:
        """Post a test message. The server records the signed-in user as sender."""
        return self._request("POST", "/messages", json={"content": content})

    def logout_everywhere(self) -> None:
        """Revoke every session of this account, on every device. Never raises."""
        if self.token is None:
            return
        try:
            self._request("POST", "/auth/logout-all")
        except ApiError:
            pass
        finally:
            self.token = None
