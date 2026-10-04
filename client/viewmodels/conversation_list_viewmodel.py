from client.api_client import ApiClient


def _label_for(conversation: dict, current_user_id: int, api_client: ApiClient) -> str:
    if conversation["kind"] == "group":
        member_count = len(conversation["participants"])
        name = conversation.get("name") or "Unnamed group"
        return f"{name}  ·  group, {member_count} members"

    other = next((p for p in conversation["participants"] if p["user_id"] != current_user_id), None)
    if other is None:
        return "Direct chat"

    try:
        other_name = api_client.get_person(other["user_id"])["name"]
    except Exception:  # noqa: BLE001 - a lookup hiccup shouldn't break the whole list
        other_name = f"user #{other['user_id']}"
    return f"Chat with {other_name}"


class ConversationListViewModel:
    """Fetches and formats the current user's conversations - these already persist
    server-side across sessions, so this is a thin read-only layer with no local
    caching yet (that's part of the later offline-support piece of the client build).
    """

    def __init__(self, api_client: ApiClient) -> None:
        self.api_client = api_client

    def load_conversations(self) -> list[dict]:
        """Returns [{"id", "label", "created_at"}, ...], newest first (server order)."""
        conversations = self.api_client.list_conversations()
        current_user_id = self.api_client.user_id
        return [
            {
                "id": conversation["id"],
                "label": _label_for(conversation, current_user_id, self.api_client),
                "created_at": conversation["created_at"],
            }
            for conversation in conversations
        ]
