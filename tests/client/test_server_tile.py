from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from client.views.server_tile import ServerTile


def test_click_invokes_callback(qtbot) -> None:
    clicked = []
    tile = ServerTile(
        name="Kairos Server",
        subtitle="192.168.1.10:8000",
        on_click=lambda: clicked.append(True),
        discovered=True,
    )
    qtbot.addWidget(tile)

    qtbot.mouseClick(tile, Qt.MouseButton.LeftButton)

    assert clicked == [True]


def test_discovered_tile_has_no_remove_button(qtbot) -> None:
    tile = ServerTile(
        name="Kairos Server", subtitle="host:port", on_click=lambda: None, discovered=True
    )
    qtbot.addWidget(tile)

    assert tile.findChildren(QPushButton) == []


def test_saved_tile_remove_button_invokes_callback_not_click(qtbot) -> None:
    clicked = []
    removed = []
    tile = ServerTile(
        name="Kairos Server",
        subtitle="host:port",
        on_click=lambda: clicked.append(True),
        discovered=False,
        on_remove=lambda: removed.append(True),
    )
    qtbot.addWidget(tile)

    remove_button = tile.findChild(QPushButton)
    qtbot.mouseClick(remove_button, Qt.MouseButton.LeftButton)

    assert removed == [True]
    assert clicked == []
