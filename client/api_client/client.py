import mimetypes
import os
from pathlib import Path

import httpx

DEFAULT_BASE_URL = "http://localhost:8000"
PLACEHOLDER_USER_HEADER = "X-Kairos-User-Id"


class ApiClient:
    """Thin wrapper around the Kairos REST backend.

    Host address is configurable via the KAIROS_SERVER_URL env var (or
    the constructor arg) rather than hardcoded, since either teammate's
    machine may be hosting the backend for a given session.
    """

    def __init__(self, base_url: str | None = None, user_id: int | None = None) -> None:
        self.base_url = base_url or os.environ.get("KAIROS_SERVER_URL", DEFAULT_BASE_URL)
        self.user_id = user_id

    def _auth_headers(self) -> dict[str, str]:
        """PLACEHOLDER auth - see server/api/dependencies.py. `user_id` must be set
        (by signing in - see client/views/auth_dialog.py) before calling any
        endpoint that needs one.
        """
        if self.user_id is None:
            raise RuntimeError("ApiClient.user_id must be set before calling this endpoint")
        return {PLACEHOLDER_USER_HEADER: str(self.user_id)}

    def health(self) -> dict:
        response = httpx.get(f"{self.base_url}/health", timeout=5)
        response.raise_for_status()
        return response.json()

    def send_message(self, sender: str, content: str) -> dict:
        response = httpx.post(
            f"{self.base_url}/messages",
            json={"sender": sender, "content": content},
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def get_server_info(self) -> dict:
        """The server's self-reported display name (see GET /server/info) - public,
        no auth required."""
        response = httpx.get(f"{self.base_url}/server/info", timeout=5)
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
        response = httpx.put(
            f"{self.base_url}/server/info",
            json={
                "display_name": display_name,
                "upload_root": upload_root,
                "max_upload_size_bytes": max_upload_size_bytes,
            },
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def search_people(self, query: str, limit: int = 20) -> list[dict]:
        """Public, no auth required - see server/api/people.py."""
        response = httpx.get(
            f"{self.base_url}/people/search", params={"q": query, "limit": limit}, timeout=5
        )
        response.raise_for_status()
        return response.json()

    def get_person(self, user_id: int) -> dict:
        """Public, no auth required - see server/api/people.py."""
        response = httpx.get(f"{self.base_url}/people/{user_id}", timeout=5)
        response.raise_for_status()
        return response.json()

    def get_my_profile(self) -> dict:
        """The caller's own profile, role included - used to decide whether to show
        admin-only UI (e.g. the Server Settings page). See GET /people/me."""
        response = httpx.get(f"{self.base_url}/people/me", headers=self._auth_headers(), timeout=5)
        response.raise_for_status()
        return response.json()

    def list_conversations(self) -> list[dict]:
        response = httpx.get(
            f"{self.base_url}/conversations", headers=self._auth_headers(), timeout=5
        )
        response.raise_for_status()
        return response.json()

    def get_conversation(self, conversation_id: int) -> dict:
        response = httpx.get(
            f"{self.base_url}/conversations/{conversation_id}",
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def add_participant(self, conversation_id: int, user_id: int, role: str = "member") -> dict:
        response = httpx.post(
            f"{self.base_url}/conversations/{conversation_id}/participants",
            json={"user_id": user_id, "role": role},
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def remove_participant(self, conversation_id: int, user_id: int) -> dict:
        response = httpx.delete(
            f"{self.base_url}/conversations/{conversation_id}/participants/{user_id}",
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def update_participant_role(self, conversation_id: int, user_id: int, role: str) -> dict:
        response = httpx.put(
            f"{self.base_url}/conversations/{conversation_id}/participants/{user_id}/role",
            json={"role": role},
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def start_direct_conversation(self, other_user_id: int) -> dict:
        """Reuses an existing 1:1 thread with this person if one already exists."""
        response = httpx.post(
            f"{self.base_url}/conversations/direct",
            json={"other_user_id": other_user_id},
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def create_group_conversation(self, name: str, member_user_ids: list[int]) -> dict:
        """The caller is auto-added as the group's admin - see
        server/services/conversation_service.py::create_group_conversation."""
        response = httpx.post(
            f"{self.base_url}/conversations/group",
            json={"name": name, "member_user_ids": member_user_ids},
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def list_messages(self, conversation_id: int, after_id: int = 0, limit: int = 50) -> list[dict]:
        """The cursor sync endpoint - `after_id` defaults to 0 for full history."""
        response = httpx.get(
            f"{self.base_url}/conversations/{conversation_id}/messages",
            params={"after_id": after_id, "limit": limit},
            headers=self._auth_headers(),
            timeout=5,
        )
        response.raise_for_status()
        return response.json()

    def send_chat_message(
        self, conversation_id: int, body: str, client_token: str | None = None
    ) -> dict:
        response = httpx.post(
            f"{self.base_url}/conversations/{conversation_id}/messages",
            json={"body": body, "client_token": client_token},
            headers=self._auth_headers(),
            timeout=5,
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
            response = httpx.post(
                f"{self.base_url}/conversations/{conversation_id}/attachments",
                files={"file": (path.name, file_obj, content_type or "application/octet-stream")},
                data=data,
                headers=self._auth_headers(),
                timeout=30,
            )
        response.raise_for_status()
        return response.json()

    def download_attachment(self, attachment_id: int, save_path: str) -> None:
        with httpx.stream(
            "GET",
            f"{self.base_url}/attachments/{attachment_id}/download",
            headers=self._auth_headers(),
            timeout=30,
        ) as response:
            response.raise_for_status()
            with open(save_path, "wb") as out_file:
                out_file.writelines(response.iter_bytes())
