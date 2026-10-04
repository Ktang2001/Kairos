"""Security audit #5/#13: text that came from people is shown, never rendered.

Qt widgets guess whether a string is HTML. A rich-text box showed a network
message '<span style="font-size:60px">SERVER HACKED</span>' as a giant red
banner on the host's screen. The server log is a plain-text box, and labels
that show names or server messages are forced to plain text.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPlainTextEdit
from pytestqt.qtbot import QtBot
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from client.views.widgets import ElidedLabel, ErrorLabel
from server import gui
from server.models import Base
from server.models.server_settings import ServerSettings
from server.services import message_service

PAYLOAD = '<span style="font-size:60px;color:red">SERVER HACKED</span><a href="http://evil">x</a>'


def test_the_server_window_shows_network_messages_as_plain_text(
    qtbot: QtBot, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite:///{(Path(tempfile.mkdtemp()) / 'm.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    db = factory()
    db.add(
        ServerSettings(
            id=1, display_name="Test", upload_root=tempfile.mkdtemp(), max_upload_size_bytes=1024
        )
    )
    db.commit()
    message_service.create_message(db, sender="<b>SYSTEM</b>", content=PAYLOAD)
    db.close()
    monkeypatch.setattr(gui, "SessionLocal", factory)

    window = gui.ServerWindow()
    qtbot.addWidget(window)
    window._poll_new_messages()

    assert isinstance(window.log, QPlainTextEdit)
    shown = window.log.toPlainText()
    assert "<b>SYSTEM</b>" in shown  # the tags are visible, i.e. not rendered
    assert PAYLOAD in shown
    engine.dispose()


@pytest.mark.parametrize("cls", [ErrorLabel, ElidedLabel])
def test_labels_showing_user_data_are_plain_text(qtbot: QtBot, cls: type) -> None:
    label = cls()
    qtbot.addWidget(label)
    assert label.textFormat() == Qt.TextFormat.PlainText
