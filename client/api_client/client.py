import mimetypes
import os
from pathlib import Path

import httpx

from client.net.cert_pinning import build_pinned_ssl_context

DEFAULT_BASE_URL = "http://localhost:8000"


class ApiClient:
    """Thin wrapper around the Kairos REST backend.

    Host address is configurable via the KAIROS_SERVER_URL env var (or
    the constructor arg) rather than hardcoded, since either teammate's
    machine may be hosting the backend for a given session.
    """

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        user_id: int | None = None,
        cert_pem: str | None = None,
    ) -> None:
        self.base_url = base_url or os.environ.get("KAIROS_SERVER_URL", DEFAULT_BASE_URL)
        self.token = token
        # Not used for auth (the token is the credential) - kept purely so client-side
        # views can tell "is this me" apart from other people (see
        # conversation_list_viewmodel.py, chat_viewmodel.py, manage_members_dialog.py).
        self.user_id = user_id
        # The pinned certificate for this server (see client/net/cert_pinning.py and
        # server/tls.py) - None only for http:// (tests, legacy local dev). A single
        # reused httpx.Client (rather than the bare module-level functions this used
        # to call) is what lets every request share one verified TLS connection pool.
        self.cert_pem = cert_pem
        verify = build_pinned_ssl_context(cert_pem) if cert_pem else True
        self._http = httpx.Client(verify=verify, timeout=5)

    def _auth_headers(self) -> dict[str, str]:
        """`token` (from signup/login - see client/views/auth_dialog.py) must be set
        before calling any endpoint that needs one. See server/api/dependencies.py.
        """
        if self.token is None:
            raise RuntimeError("ApiClient.token must be set before calling this endpoint")
        return {"Authorization": f"Bearer {self.token}"}

    def logout(self) -> None:
        self._http.post(f"{self.base_url}/auth/logout", headers=self._auth_headers())
        self.token = None

    def health(self) -> dict:
        response = self._http.get(f"{self.base_url}/health")
        response.raise_for_status()
        return response.json()

    def send_message(self, sender: str, content: str) -> dict:
        response = self._http.post(
            f"{self.base_url}/messages",
            json={"sender": sender, "content": content},
        )
        response.raise_for_status()
        return response.json()

    def get_server_info(self) -> dict:
        """The server's self-reported display name (see GET /server/info) - public,
        no auth required."""
        response = self._http.get(f"{self.base_url}/server/info")
        response.raise_for_status()
        return response.json()

    def update_server_info(
        self,
        display_name: str | None = None,
        upload_root: str | None = None,
        max_upload_size_bytes: int | None = None,
    ) -> dict:
        """Requires the caller to hold the global admin role server-side (see
        server/api/dependencies.py::require_global_admin) - a non-admin gets a 403.
        Any field left as None is left unchanged.
        """
        response = self._http.put(
            f"{self.base_url}/server/info",
            json={
                "display_name": display_name,
                "upload_root": upload_root,
                "max_upload_size_bytes": max_upload_size_bytes,
            },
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def search_people(self, query: str, limit: int = 20) -> list[dict]:
        """Public, no auth required - see server/api/people.py."""
        response = self._http.get(
            f"{self.base_url}/people/search", params={"q": query, "limit": limit}
        )
        response.raise_for_status()
        return response.json()

    def get_person(self, user_id: int) -> dict:
        """Public, no auth required - see server/api/people.py."""
        response = self._http.get(f"{self.base_url}/people/{user_id}")
        response.raise_for_status()
        return response.json()

    def get_my_profile(self) -> dict:
        """The caller's own profile, role included - used to decide whether to show
        admin-only UI (e.g. the Server Settings page). See GET /people/me."""
        response = self._http.get(f"{self.base_url}/people/me", headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

    def list_conversations(self) -> list[dict]:
        response = self._http.get(f"{self.base_url}/conversations", headers=self._auth_headers())
        response.raise_for_status()
        return response.json()

    def get_conversation(self, conversation_id: int) -> dict:
        response = self._http.get(
            f"{self.base_url}/conversations/{conversation_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def add_participant(self, conversation_id: int, user_id: int, role: str = "member") -> dict:
        response = self._http.post(
            f"{self.base_url}/conversations/{conversation_id}/participants",
            json={"user_id": user_id, "role": role},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def remove_participant(self, conversation_id: int, user_id: int) -> dict:
        response = self._http.delete(
            f"{self.base_url}/conversations/{conversation_id}/participants/{user_id}",
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def update_participant_role(self, conversation_id: int, user_id: int, role: str) -> dict:
        response = self._http.put(
            f"{self.base_url}/conversations/{conversation_id}/participants/{user_id}/role",
            json={"role": role},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def start_direct_conversation(self, other_user_id: int) -> dict:
        """Reuses an existing 1:1 thread with this person if one already exists."""
        response = self._http.post(
            f"{self.base_url}/conversations/direct",
            json={"other_user_id": other_user_id},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def create_group_conversation(self, name: str, member_user_ids: list[int]) -> dict:
        """The caller is auto-added as the group's admin - see
        server/services/conversation_service.py::create_group_conversation."""
        response = self._http.post(
            f"{self.base_url}/conversations/group",
            json={"name": name, "member_user_ids": member_user_ids},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def list_messages(self, conversation_id: int, after_id: int = 0, limit: int = 50) -> list[dict]:
        """The cursor sync endpoint - `after_id` defaults to 0 for full history."""
        response = self._http.get(
            f"{self.base_url}/conversations/{conversation_id}/messages",
            params={"after_id": after_id, "limit": limit},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def send_chat_message(
        self, conversation_id: int, body: str, client_token: str | None = None
    ) -> dict:
        response = self._http.post(
            f"{self.base_url}/conversations/{conversation_id}/messages",
            json={"body": body, "client_token": client_token},
            headers=self._auth_headers(),
        )
        response.raise_for_status()
        return response.json()

    def upload_attachment(
        self,
        conversation_id: int,
        file_path: str,
        caption: str | None = None,
        client_token: str | None = None,
    ) -> dict:
        """No type restriction - video/audio/documents/anything, per spec. The
        server enforces the actual size cap (see server/services/attachment_service.py);
        this is just a chunked multipart upload of whatever file was picked.
        """
        path = Path(file_path)
        content_type, _ = mimetypes.guess_type(path.name)
        data = {}
        if caption:
            data["caption"] = caption
        if client_token:
            data["client_token"] = client_token

        with path.open("rb") as file_obj:
            response = self._http.post(
                f"{self.base_url}/conversations/{conversation_id}/attachments",
                files={"file": (path.name, file_obj, content_type or "application/octet-stream")},
                data=data,
                headers=self._auth_headers(),
                timeout=30,
            )
        response.raise_for_status()
        return response.json()

    def download_attachment(self, attachment_id: int, save_path: str) -> None:
        with self._http.stream(
            "GET",
            f"{self.base_url}/attachments/{attachment_id}/download",
            headers=self._auth_headers(),
            timeout=30,
        ) as response:
            response.raise_for_status()
            with open(save_path, "wb") as out_file:
                out_file.writelines(response.iter_bytes())
