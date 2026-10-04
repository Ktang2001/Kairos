"""Every request the desktop client makes to the Kairos server.

One ``ApiClient`` per signed-in user. Each method is one API route; they all go through
``_request``, which adds the sign-in token, turns every failure into an ``ApiError`` with a message
fit to show, and tells the app whether the host is reachable (the offline banner) or the session has
ended (back to login).

MERGE-CRITICAL: new methods (chat, conversations, people...) must call ``self._request(...)`` like
the ones below, not ``httpx`` directly. Calling httpx directly skips the token, the error messages,
the offline banner and the session-expired handling. They must also not send a user id header (e.g.
``X-Kairos-User-Id``) instead of the token: the server must not trust a client to say who it is.
Guarded by: tests/client/test_api_client.py and test_app_robustness.py.
"""

import os
from collections.abc import Callable
from typing import Any

import httpx

#: 127.0.0.1 rather than "localhost": see normalise_base_url.
DEFAULT_BASE_URL = "http://127.0.0.1:8000"

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

    ``localhost`` is rewritten to ``127.0.0.1``. On Windows, "localhost"
    resolves to the IPv6 address ::1 first; the server listens on IPv4 only,
    so every request waited ~2 seconds for that attempt to fail before
    falling back -- slow enough that people pressed Send twice.
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
    # MERGE-CRITICAL: keep this rewrite. Without it every request on Windows
    # waits ~2 s for an IPv6 attempt first -- slow enough that people pressed
    # Send twice. Guarded by: tests/client/test_api_client.py.
    if url.host == "localhost":
        candidate = str(url.copy_with(host="127.0.0.1")).rstrip("/")
    return candidate


def _unreachable_message(base_url: str) -> str:
    """The message for a host that refused or never answered the connection."""
    return f"Can't reach the server at {base_url}. Is it running, and is the address right?"


def _timeout_message(base_url: str) -> str:
    """The message for a host that connected but took longer than the timeout to reply."""
    return f"The server at {base_url} took too long to answer."


def is_connection_error(message: str) -> bool:
    """True for the two messages that mean "the host didn't answer at all".

    Screens with the app-wide offline banner use this to avoid repeating the
    same problem in their own error line. Kept next to the two functions that
    build those messages so the wording can't drift apart.
    """
    return message.startswith("Can't reach the server at ") or (
        message.startswith("The server at ") and message.endswith(" took too long to answer.")
    )


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

    Two optional hooks let the app react to the connection as a whole rather
    than error by error (both may be called from a background thread):

    * ``on_connection_changed(reachable)`` after every request: False when the
      host could not be reached, True when it answered (even with an error).
    * ``on_session_expired()`` when a signed-in request is refused with 401,
      i.e. the token was revoked, expired, or signed out elsewhere.
    """

    def __init__(self, base_url: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = normalise_base_url(
            base_url or os.environ.get("KAIROS_SERVER_URL", DEFAULT_BASE_URL)
        )
        self.timeout = timeout
        self.token: str | None = None
        self.on_connection_changed: Callable[[bool], None] | None = None
        self.on_session_expired: Callable[[], None] | None = None

    def _request(self, method: str, path: str, *, json: dict | None = None) -> Any:
        """Send one request with the token, and return the decoded JSON reply (None if empty).
        Raises ApiError on any failure, after reporting reachability and session expiry through the
        hooks.
        """
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
            self._notify_connection(False)
            raise ApiError(_timeout_message(self.base_url)) from None
        except httpx.TransportError:
            self._notify_connection(False)
            raise ApiError(_unreachable_message(self.base_url)) from None

        self._notify_connection(True)
        if response.is_success:
            return response.json() if response.content else None
        if (
            response.status_code == 401
            and self.token is not None
            and not path.startswith("/auth/logout")
            and self.on_session_expired is not None
        ):
            self.on_session_expired()
        raise ApiError(_error_message(response), response.status_code)

    def _notify_connection(self, reachable: bool) -> None:
        """Tell the app whether the host answered (feeds the offline banner)."""
        if self.on_connection_changed is not None:
            self.on_connection_changed(reachable)

    def health(self) -> dict:
        """Ask the server if it is up; returns {"status": "ok"}."""
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
        """The signed-in user as the server knows them now (their role may have changed)."""
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

    # ------------------------------------------------------------- teams

    def list_teams(self) -> list[dict]:
        """Teams you belong to (admins: every team), each with lead and member count."""
        return self._request("GET", "/teams")

    def get_team(self, team_id: int) -> dict:
        """One team with its full member list."""
        return self._request("GET", f"/teams/{team_id}")

    def create_team(self, name: str) -> dict:
        """Create a team; you become its lead. Admins and project leads only."""
        return self._request("POST", "/teams", json={"name": name})

    def rename_team(self, team_id: int, name: str) -> dict:
        """Rename a team (its lead or an admin)."""
        return self._request("PATCH", f"/teams/{team_id}", json={"name": name})

    def delete_team(self, team_id: int) -> None:
        """Delete a team (its lead or an admin)."""
        self._request("DELETE", f"/teams/{team_id}")

    def add_member(self, team_id: int, email: str) -> dict:
        """Add someone to a team by their email."""
        return self._request("POST", f"/teams/{team_id}/members", json={"email": email})

    def remove_member(self, team_id: int, user_id: int) -> None:
        """Remove someone, or leave the team when ``user_id`` is your own id."""
        self._request("DELETE", f"/teams/{team_id}/members/{user_id}")

    def change_lead(self, team_id: int, user_id: int) -> dict:
        """Make another member the team's lead."""
        return self._request("PUT", f"/teams/{team_id}/lead", json={"user_id": user_id})

    # ------------------------------------------------------- users (admin)

    def list_users(self) -> list[dict]:
        """Every account with its role (admins only)."""
        return self._request("GET", "/users")

    def set_role(self, user_id: int, role: str) -> dict:
        """Change someone's role (admins only, never your own)."""
        return self._request("PUT", f"/users/{user_id}/role", json={"role": role})

    # ------------------------------------------------------- attachments

    def upload_attachment(
        self, path: "os.PathLike[str] | str", kind: str, content: str = ""
    ) -> dict:
        """Upload a file, image or audio clip as a message.

        TODO(attachments): not built yet -- nothing calls this until
        ``HomeViewModel._send_with_attachment`` is connected. Suggested shape:

        * POST multipart/form-data to a new route (e.g. ``/messages/attachments``)
          with the file, ``kind`` ("file" / "image" / "audio") and the optional
          text ``content``. httpx does multipart with
          ``files={"file": (name, open(path, "rb"))}, data={"kind": kind, ...}``.
        * ``_request`` above only sends JSON; give it ``files=`` / ``data=``
          parameters (keep the auth header, error handling and the
          connection/expiry hooks it already has).
        * Return the server's stored message (its ``MessageOut``).
        """
        raise NotImplementedError("Attachment upload isn't built yet - see TODO(attachments).")
