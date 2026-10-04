from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ServerTile(QFrame):
    """One clickable server card - used for both live-discovered and saved
    entries. `discovered` only changes the badge text; click behavior and the
    optional remove affordance are controlled entirely by the caller.
    """

    def __init__(
        self,
        name: str,
        subtitle: str,
        on_click: Callable[[], None],
        discovered: bool,
        on_remove: Callable[[], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("serverTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(subtitle)
        self._on_click = on_click

        self.name_label = QLabel(name)
        self.name_label.setObjectName("serverTileName")

        badge = "Discovered" if discovered else "Saved"
        self.subtitle_label = QLabel(f"{subtitle}  ·  {badge}")
        self.subtitle_label.setProperty("muted", True)

        text_column = QVBoxLayout()
        text_column.addWidget(self.name_label)
        text_column.addWidget(self.subtitle_label)

        row = QHBoxLayout()
        row.addLayout(text_column, 1)

        if on_remove is not None:
            remove_button = QPushButton("✕")
            remove_button.setToolTip("Remove from saved servers")
            remove_button.setFixedWidth(28)
            remove_button.clicked.connect(lambda: on_remove())
            row.addWidget(remove_button)

        self.setLayout(row)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._on_click()
        super().mousePressEvent(event)
