import uuid

from client.api_client import ApiClient


class ChatViewModel:
    """Owns one conversation's cursor position and a small sender-name cache.

    Polling-only for now (calls the same cursor endpoint - GET .../messages?after_id=
    - the realtime WebSocket layer would later push to, see server/api/ws_chat.py).
    No local offline cache/outbox yet; that's a later increment.
    """

    def __init__(self, api_client: ApiClient, conversation_id: int) -> None:
        self.api_client = api_client
        self.conversation_id = conversation_id
        self._last_seen_id = 0
        self._sender_names: dict[int, str] = {}

    def fetch_new_messages(self) -> list[dict]:
        messages = self.api_client.list_messages(self.conversation_id, after_id=self._last_seen_id)
        for message in messages:
            self._last_seen_id = max(self._last_seen_id, message["id"])
        return messages

    def sender_label(self, user_id: int) -> str:
        if user_id == self.api_client.user_id:
            return "You"
        if user_id not in self._sender_names:
            try:
                self._sender_names[user_id] = self.api_client.get_person(user_id)["name"]
            except Exception:  # noqa: BLE001 - a lookup hiccup shouldn't break the thread view
                self._sender_names[user_id] = f"user #{user_id}"
        return self._sender_names[user_id]

    def send_text(self, body: str) -> dict:
        return self.api_client.send_chat_message(
            self.conversation_id, body=body, client_token=uuid.uuid4().hex
        )

    def send_attachment(self, file_path: str, caption: str | None = None) -> dict:
        return self.api_client.upload_attachment(
            self.conversation_id, file_path, caption=caption, client_token=uuid.uuid4().hex
        )

    def download_attachment(self, attachment_id: int, save_path: str) -> None:
        self.api_client.download_attachment(attachment_id, save_path)
