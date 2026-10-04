from client.viewmodels.conversation_list_viewmodel import ConversationListViewModel


class _FakeApiClient:
    def __init__(self, user_id: int, conversations: list[dict], people: dict[int, dict]) -> None:
        self.user_id = user_id
        self._conversations = conversations
        self._people = people

    def list_conversations(self) -> list[dict]:
        return self._conversations

    def get_person(self, user_id: int) -> dict:
        return self._people[user_id]


def test_group_conversation_label_shows_name_and_member_count() -> None:
    api = _FakeApiClient(
        user_id=1,
        conversations=[
            {
                "id": 1,
                "kind": "group",
                "name": "Project Team",
                "created_at": "2026-10-01T00:00:00",
                "participants": [
                    {"user_id": 1, "role": "admin"},
                    {"user_id": 2, "role": "member"},
                    {"user_id": 3, "role": "member"},
                ],
            }
        ],
        people={},
    )

    result = ConversationListViewModel(api).load_conversations()

    assert result[0]["label"] == "Project Team  ·  group, 3 members"


def test_direct_conversation_label_shows_other_persons_name() -> None:
    api = _FakeApiClient(
        user_id=1,
        conversations=[
            {
                "id": 2,
                "kind": "direct",
                "name": None,
                "created_at": "2026-10-01T00:00:00",
                "participants": [
                    {"user_id": 1, "role": "member"},
                    {"user_id": 2, "role": "member"},
                ],
            }
        ],
        people={2: {"id": 2, "name": "Bob Builder", "email": "bob@example.com"}},
    )

    result = ConversationListViewModel(api).load_conversations()

    assert result[0]["label"] == "Chat with Bob Builder"


def test_direct_conversation_falls_back_when_person_lookup_fails() -> None:
    api = _FakeApiClient(
        user_id=1,
        conversations=[
            {
                "id": 2,
                "kind": "direct",
                "name": None,
                "created_at": "2026-10-01T00:00:00",
                "participants": [
                    {"user_id": 1, "role": "member"},
                    {"user_id": 2, "role": "member"},
                ],
            }
        ],
        people={},
    )

    result = ConversationListViewModel(api).load_conversations()

    assert result[0]["label"] == "Chat with user #2"
