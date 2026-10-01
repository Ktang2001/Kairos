"""Small widgets shared by the screens."""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QPalette, QResizeEvent
from PySide6.QtWidgets import QLabel, QSizePolicy, QWidget

#: Error red for light themes: 4.8:1 against Qt's light grey background.
ERROR_RED_ON_LIGHT = "#c0392b"
#: Error red for dark themes. The light-theme red is only 3.1:1 on the
#: Windows 11 dark background (#1e1e1e) -- below the 4.5:1 readability
#: minimum (WCAG AA) -- while this one is about 6:1.
ERROR_RED_ON_DARK = "#ff6b6b"


def is_dark(widget: QWidget) -> bool:
    return widget.palette().color(QPalette.ColorRole.Window).lightness() < 128


class ErrorLabel(QLabel):
    """A wrapping, initially hidden label in a red that is readable on the
    current theme, re-picked if the user switches between light and dark
    while the app is open.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colour: str | None = None
        # Messages can quote what the user or server sent; never render HTML.
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)
        self.setVisible(False)
        self._apply_colour()

    def show_message(self, message: str) -> None:
        """Show ``message``, or hide the label when it is empty."""
        self.setText(message)
        self.setVisible(bool(message))

    def changeEvent(self, event: QEvent) -> None:
        if event.type() == QEvent.Type.PaletteChange:
            self._apply_colour()
        super().changeEvent(event)

    def _apply_colour(self) -> None:
        colour = ERROR_RED_ON_DARK if is_dark(self) else ERROR_RED_ON_LIGHT
        # setStyleSheet itself sends a PaletteChange event, which calls this
        # again: only restyle when the colour really changes, or it recurses
        # forever.
        if colour != self._colour:
            self._colour = colour
            self.setStyleSheet(f"color: {colour};")


class ElidedLabel(QLabel):
    """One line of text that is cut short with "…" when there is no room,
    instead of forcing the window wider. The full text is in the tooltip.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # Shows user-chosen names: plain text, so a name like "<b>Admin</b>"
        # is displayed literally instead of being rendered.
        self.setTextFormat(Qt.TextFormat.PlainText)
        # Ignored horizontally: the label takes whatever width the layout
        # offers rather than demanding room for its whole text.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._full_text = ""
        self.set_full_text(text)

    @property
    def full_text(self) -> str:
        return self._full_text

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(
            self.fontMetrics().elidedText(
                self._full_text, Qt.TextElideMode.ElideRight, self.width()
            )
        )
