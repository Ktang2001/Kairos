from client.viewmodels.chat_viewmodel import ChatViewModel


class _FakeApiClient:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.sent_messages: list[dict] = []
        self.uploaded: list[dict] = []
        self.downloaded: list[dict] = []
        self._messages_by_page: list[list[dict]] = []
        self._people = {2: {"id": 2, "name": "Bob Builder"}}

    def queue_messages_page(self, messages: list[dict]) -> None:
        self._messages_by_page.append(messages)

    def list_messages(self, conversation_id: int, after_id: int = 0, limit: int = 50) -> list[dict]:
        if not self._messages_by_page:
            return []
        return self._messages_by_page.pop(0)

    def get_person(self, user_id: int) -> dict:
        return self._people[user_id]

    def send_chat_message(self, conversation_id: int, body: str, client_token=None) -> dict:
        message = {"id": 99, "conversation_id": conversation_id, "body": body}
        self.sent_messages.append(message)
        return message

    def upload_attachment(
        self, conversation_id, file_path, caption=None, client_token=None
    ) -> dict:
        record = {"conversation_id": conversation_id, "file_path": file_path, "caption": caption}
        self.uploaded.append(record)
        return record

    def download_attachment(self, attachment_id: int, save_path: str) -> None:
        self.downloaded.append({"attachment_id": attachment_id, "save_path": save_path})


def test_fetch_new_messages_advances_cursor() -> None:
    api = _FakeApiClient(user_id=1)
    api.queue_messages_page([{"id": 5, "sender_user_id": 1, "body": "hi"}])
    vm = ChatViewModel(api, conversation_id=7)

    messages = vm.fetch_new_messages()

    assert messages[0]["id"] == 5
    assert vm._last_seen_id == 5


def test_sender_label_returns_you_for_current_user() -> None:
    api = _FakeApiClient(user_id=1)
    vm = ChatViewModel(api, conversation_id=7)

    assert vm.sender_label(1) == "You"


def test_sender_label_resolves_and_caches_other_user() -> None:
    api = _FakeApiClient(user_id=1)
    vm = ChatViewModel(api, conversation_id=7)

    assert vm.sender_label(2) == "Bob Builder"
    # Removing the person from the fake API proves the second call used the cache.
    del api._people[2]
    assert vm.sender_label(2) == "Bob Builder"


def test_send_text_delegates_to_api_client() -> None:
    api = _FakeApiClient(user_id=1)
    vm = ChatViewModel(api, conversation_id=7)

    vm.send_text("hello")

    assert api.sent_messages[0]["body"] == "hello"


def test_send_attachment_and_download_delegate_to_api_client() -> None:
    api = _FakeApiClient(user_id=1)
    vm = ChatViewModel(api, conversation_id=7)

    vm.send_attachment("/tmp/file.txt", caption="here")
    vm.download_attachment(attachment_id=3, save_path="/tmp/out.txt")

    assert api.uploaded[0]["file_path"] == "/tmp/file.txt"
    assert api.downloaded[0]["attachment_id"] == 3
