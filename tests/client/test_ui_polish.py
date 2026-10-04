"""Usability checks for the shared widgets used by the Teams and Users pages:

1. error text readable on light and dark themes
2. a long name is shortened with "…" instead of stretching the window
"""

import pytest
from PySide6.QtGui import QColor, QPalette
from pytestqt.qtbot import QtBot

from client.views.widgets import ERROR_RED_ON_DARK, ERROR_RED_ON_LIGHT, ElidedLabel, ErrorLabel


def _contrast(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two #rrggbb colours."""

    def luminance(colour: str) -> float:
        def channel(c: float) -> float:
            return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = (int(colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    high, low = sorted((luminance(foreground), luminance(background)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _palette(window_colour: str) -> QPalette:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(window_colour))
    return palette


@pytest.mark.parametrize(
    ("background", "expected"),
    [
        ("#1e1e1e", ERROR_RED_ON_DARK),  # Windows 11 dark
        ("#2d2d2d", ERROR_RED_ON_DARK),  # typical Linux dark theme
        ("#f0f0f0", ERROR_RED_ON_LIGHT),  # Windows light
        ("#efefef", ERROR_RED_ON_LIGHT),  # Fusion light
    ],
)
def test_error_text_is_readable_on_the_theme(qtbot: QtBot, background: str, expected: str) -> None:
    label = ErrorLabel()
    qtbot.addWidget(label)
    label.setPalette(_palette(background))

    assert expected in label.styleSheet()
    assert _contrast(expected, background) >= 4.5


def test_the_old_red_really_was_unreadable_on_dark() -> None:
    """Documents why the dark-theme colour exists."""
    assert _contrast(ERROR_RED_ON_LIGHT, "#1e1e1e") < 4.5


def test_the_error_colour_follows_a_theme_switch(qtbot: QtBot) -> None:
    label = ErrorLabel()
    qtbot.addWidget(label)
    label.setPalette(_palette("#f0f0f0"))
    assert ERROR_RED_ON_LIGHT in label.styleSheet()
    label.setPalette(_palette("#1e1e1e"))
    assert ERROR_RED_ON_DARK in label.styleSheet()


# --------------------------------------------------------- 2. long names


def test_a_long_name_is_shortened_not_stretching_its_column(qtbot: QtBot) -> None:
    long_name = "Maximilian " * 9
    label = ElidedLabel(long_name.strip())
    qtbot.addWidget(label)
    label.resize(120, 20)
    label.show()
    qtbot.wait(20)
    assert label.text().endswith("…")
    assert label.full_text == long_name.strip()
    assert label.toolTip() == label.full_text


def test_widening_reveals_more_of_a_long_name(qtbot: QtBot) -> None:
    label = ElidedLabel("Maximilian " * 9)
    qtbot.addWidget(label)
    label.resize(120, 20)
    label.show()
    qtbot.wait(20)
    narrow = len(label.text())
    label.resize(1400, 20)
    qtbot.wait(20)
    assert len(label.text()) > narrow
