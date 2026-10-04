"""Tests for the Attach button on the Messages tab (UI only).

Choosing a file, image or audio clip is built; uploading and storing it is
not yet (see ``TODO(attachments)``). These tests pin down the UI part and
guard the hand-off: until upload exists, sending with an attachment must say
so plainly and lose nothing.
"""

import threading
from pathlib import Path

import pytest
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient
from client.viewmodels.attachments import (
    KIND_FILTERS,
    AttachmentKind,
    PendingAttachment,
    human_size,
)
from client.viewmodels.background import BackgroundRunner
from client.viewmodels.home_viewmodel import HomeViewModel
from client.viewmodels.login_viewmodel import Session
from client.views.home_view import HomeView

REPO = Path(__file__).resolve().parents[2]
WAIT_MS = 5000


class FakeClient:
    """Records text messages; never touches the network."""

    def __init__(self) -> None:
        self.base_url = "http://127.0.0.1:9"
        self.token = "t"
        self.sent: list[str] = []
        self.gate = threading.Event()
        self.gate.set()

    def send_message(self, content: str) -> dict:
        self.sent.append(content)
        self.gate.wait(5)
        return {"id": 1, "sender": "Nick", "content": content}

    def logout(self) -> None:
        self.token = None


@pytest.fixture
def client() -> FakeClient:
    fake = FakeClient()
    yield fake
    fake.gate.set()


@pytest.fixture
def view(qtbot: QtBot, client: FakeClient) -> HomeView:
    session = Session(
        client=client, user={"id": 1, "name": "Nick", "email": "n@x.co", "role": "member"}
    )
    home = HomeView(HomeViewModel(session, runner=BackgroundRunner()))
    qtbot.addWidget(home)
    home.show()
    home.tabs.setCurrentWidget(home.messages_tab)
    return home


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    file = tmp_path / "photo.png"
    file.write_bytes(b"\x89PNG" + b"x" * 2044)  # 2 KB
    return file


def _pick(view: HomeView, path: Path | str, kind: AttachmentKind) -> list[AttachmentKind]:
    """Choose ``path`` through the Attach menu, with the dialog replaced."""
    asked: list[AttachmentKind] = []
    view.pick_file = lambda k: asked.append(k) or str(path)
    view.attach_actions[kind].trigger()
    return asked


# ------------------------------------------------------------- the button


def test_the_messages_tab_has_an_attach_button_with_three_choices(view: HomeView) -> None:
    assert view.attach_button.isVisible()
    assert view.attach_button.text() == "Attach"
    labels = [action.text() for action in view.attach_menu.actions()]
    assert labels == ["File…", "Image…", "Audio…"]


@pytest.mark.parametrize("kind", list(AttachmentKind))
def test_each_choice_opens_the_picker_for_that_kind(
    view: HomeView, photo: Path, kind: AttachmentKind
) -> None:
    assert _pick(view, photo, kind) == [kind]
    assert view.viewmodel.attachment.kind == kind


def test_the_pickers_filter_to_sensible_file_types() -> None:
    assert "*.png" in KIND_FILTERS[AttachmentKind.IMAGE]
    assert "*.jpg" in KIND_FILTERS[AttachmentKind.IMAGE]
    assert "*.mp3" in KIND_FILTERS[AttachmentKind.AUDIO]
    assert "*.wav" in KIND_FILTERS[AttachmentKind.AUDIO]
    assert KIND_FILTERS[AttachmentKind.FILE] == "All files (*)"


# ------------------------------------------------------------- the chip


def test_a_picked_file_is_shown_with_its_size(view: HomeView, photo: Path) -> None:
    _pick(view, photo, AttachmentKind.IMAGE)
    assert view.attachment_row.isVisible()
    assert view.attachment_label.full_text == "🖼 photo.png (2 KB)"


def test_cancelling_the_picker_attaches_nothing(view: HomeView) -> None:
    _pick(view, "", AttachmentKind.FILE)
    assert view.viewmodel.attachment is None
    assert not view.attachment_row.isVisible()


def test_the_x_button_removes_the_attachment(view: HomeView, photo: Path) -> None:
    _pick(view, photo, AttachmentKind.IMAGE)
    view.remove_attachment_button.click()
    assert view.viewmodel.attachment is None
    assert not view.attachment_row.isVisible()


def test_picking_again_replaces_the_attachment(view: HomeView, photo: Path, tmp_path: Path) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"ID3" * 10)
    _pick(view, photo, AttachmentKind.IMAGE)
    _pick(view, song, AttachmentKind.AUDIO)
    assert view.viewmodel.attachment.name == "song.mp3"
    assert view.attachment_label.full_text.startswith("🎵 song.mp3")


def test_a_file_that_vanished_is_reported(view: HomeView, tmp_path: Path) -> None:
    _pick(view, tmp_path / "gone.pdf", AttachmentKind.FILE)
    assert view.viewmodel.attachment is None
    assert view.error_label.text() == "gone.pdf no longer exists."


def test_a_folder_is_refused(view: HomeView, tmp_path: Path) -> None:
    folder = tmp_path / "notes"
    folder.mkdir()
    _pick(view, folder, AttachmentKind.FILE)
    assert view.viewmodel.attachment is None
    assert "is a folder" in view.error_label.text()


# ------------------------------------------------- sending (not built yet)


def test_sending_with_an_attachment_explains_and_loses_nothing(
    qtbot: QtBot, view: HomeView, client: FakeClient, photo: Path
) -> None:
    _pick(view, photo, AttachmentKind.IMAGE)
    view.message_input.setText("here's the logo")
    view._send()
    qtbot.wait(50)

    assert "aren't connected to the server yet" in view.error_label.text()
    assert "photo.png" in view.error_label.text()
    assert view.message_input.text() == "here's the logo"
    assert view.viewmodel.attachment is not None
    assert client.sent == []  # the text didn't go out on its own either


def test_an_attachment_alone_with_no_text_also_explains(
    qtbot: QtBot, view: HomeView, photo: Path
) -> None:
    _pick(view, photo, AttachmentKind.IMAGE)
    view._send()
    assert "aren't connected" in view.error_label.text()


def test_plain_messages_still_send_normally(
    qtbot: QtBot, view: HomeView, client: FakeClient
) -> None:
    view.message_input.setText("hello")
    with qtbot.waitSignal(view.viewmodel.message_sent, timeout=WAIT_MS):
        view._send()
    assert client.sent == ["hello"]


def test_attach_is_locked_while_a_message_is_sending(
    qtbot: QtBot, view: HomeView, client: FakeClient
) -> None:
    client.gate.clear()
    view.message_input.setText("hello")
    view._send()
    assert not view.attach_button.isEnabled()
    with qtbot.waitSignal(view.viewmodel.message_sent, timeout=WAIT_MS):
        client.gate.set()
    assert view.attach_button.isEnabled()


# ------------------------------------------------------------ hand-off


def test_the_upload_call_is_a_clear_stub() -> None:
    with pytest.raises(NotImplementedError, match="TODO\\(attachments\\)"):
        ApiClient("http://127.0.0.1:9").upload_attachment("x.png", "image")


@pytest.mark.parametrize(
    "path",
    [
        "client/viewmodels/home_viewmodel.py",
        "client/api_client/client.py",
        "server/api/messages.py",
        "server/services/message_service.py",
        "server/models/message.py",
        "server/api/protection.py",
    ],
)
def test_the_handoff_notes_are_where_the_partner_will_look(path: str) -> None:
    assert "TODO(attachments)" in (REPO / path).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("size", "text"),
    [(0, "0 B"), (999, "999 B"), (2048, "2 KB"), (5_300_000, "5.1 MB")],
)
def test_sizes_read_naturally(size: int, text: str) -> None:
    assert human_size(size) == text


def test_pending_attachment_from_a_real_file(photo: Path) -> None:
    attachment = PendingAttachment.from_path(photo, AttachmentKind.IMAGE)
    assert (attachment.name, attachment.size_bytes) == ("photo.png", 2048)
