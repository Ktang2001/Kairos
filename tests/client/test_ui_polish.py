"""Tests for the usability fixes found by testing the UI by hand:

1. error text readable on light and dark themes
2. a long name does not stretch the window
3. the cursor starts where the user needs to type
4. an error clears as soon as the user starts fixing it
5. the form does not stretch across a maximised window
6. inputs stop at the server's length limits
"""

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from pytestqt.qtbot import QtBot

from client.api_client import ApiClient
from client.main import SIGNED_IN_SIZE, MainWindow
from client.settings import ClientSettings
from client.viewmodels.login_viewmodel import Session
from client.views.login_view import MAX_FORM_WIDTH
from client.views.widgets import ERROR_RED_ON_DARK, ERROR_RED_ON_LIGHT, ErrorLabel
from shared.account_rules import MAX_EMAIL_LENGTH, MAX_NAME_LENGTH
from shared.message_rules import MAX_CONTENT_LENGTH

WAIT_MS = 3000


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


def _fake_session(name: str = "Nick", role: str = "member") -> Session:
    """A signed-in session whose requests fail at once without leaving this
    computer. (A LAN address would hang each request for the full 5 s
    timeout, or reach whatever device really has that address.)
    """
    return Session(
        client=ApiClient("http://127.0.0.1:9"),
        user={"id": 1, "name": name, "email": "nick@example.com", "role": role},
    )


@pytest.fixture
def window(qtbot: QtBot, settings: ClientSettings) -> MainWindow:
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.resize(480, 420)
    win.show()
    qtbot.waitExposed(win)
    return win


# ------------------------------------------------------- 1. readable errors


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


def test_a_long_name_is_shortened_not_stretching_the_window(
    qtbot: QtBot, window: MainWindow
) -> None:
    long_name = "Maximilian " * 9
    window._show_home(_fake_session(name=long_name.strip()))
    qtbot.wait(50)

    label = window.home_view.signed_in_label
    # The window widens to its signed-in size for the Teams screen -- and no
    # further, however long the name.
    assert window.width() == SIGNED_IN_SIZE[0]
    assert label.text().endswith("…")
    assert label.full_text == f"Signed in as {long_name.strip()} (Member)"
    assert label.toolTip() == label.full_text


def test_a_short_name_is_shown_in_full(qtbot: QtBot, window: MainWindow) -> None:
    # Wider than the default: the headless test platform draws every letter
    # as a wide box, so text takes more room here than with real fonts.
    window.resize(900, 420)
    window._show_home(_fake_session(name="Nick", role="project_lead"))
    qtbot.wait(50)
    assert window.home_view.signed_in_label.text() == "Signed in as Nick (Project Lead)"


def test_widening_the_window_reveals_more_of_a_long_name(qtbot: QtBot, window: MainWindow) -> None:
    window._show_home(_fake_session(name="Maximilian " * 9))
    qtbot.wait(50)
    narrow = len(window.home_view.signed_in_label.text())
    window.resize(1400, 420)
    qtbot.wait(50)
    assert len(window.home_view.signed_in_label.text()) > narrow


# ------------------------------------------------------- 3. starting focus


def test_a_returning_user_starts_in_the_password_field(
    qtbot: QtBot, settings: ClientSettings
) -> None:
    settings.server_url = "http://192.168.1.5:8000"
    settings.last_email = "nick@example.com"
    win = MainWindow(settings)
    qtbot.addWidget(win)
    win.show()
    win.activateWindow()
    qtbot.waitUntil(lambda: win.login_view.password_input.hasFocus(), timeout=WAIT_MS)


def test_a_first_time_user_starts_in_the_email_field(qtbot: QtBot, window: MainWindow) -> None:
    """The server field is pre-filled with the default, so email is first empty field."""
    window.activateWindow()
    qtbot.waitUntil(lambda: window.login_view.email_input.hasFocus(), timeout=WAIT_MS)


def test_a_blank_server_field_gets_the_cursor_first(window: MainWindow) -> None:
    view = window.login_view
    view.server_input.clear()
    view.focus_first_empty_field()
    window.activateWindow()
    assert view.focusWidget() is view.server_input


# ------------------------------------------------ 4. errors clear on typing


def _show_password_error(qtbot: QtBot, window: MainWindow) -> None:
    view = window.login_view
    view.email_input.setText("nick@example.com")
    view.password_input.clear()
    view.submit_sign_in()
    assert not view.error_label.isHidden()


def test_typing_in_any_field_clears_the_error(qtbot: QtBot, window: MainWindow) -> None:
    _show_password_error(qtbot, window)
    qtbot.keyClicks(window.login_view.password_input, "p")
    assert window.login_view.error_label.isHidden()


@pytest.mark.parametrize("field", ["server_input", "email_input"])
def test_editing_other_fields_also_clears_it(qtbot: QtBot, window: MainWindow, field: str) -> None:
    _show_password_error(qtbot, window)
    qtbot.keyClick(getattr(window.login_view, field), Qt.Key.Key_Backspace)
    assert window.login_view.error_label.isHidden()


def test_filling_a_field_in_code_does_not_clear_the_error(qtbot: QtBot, window: MainWindow) -> None:
    """Only the user's own typing counts, so the app never hides a message by itself."""
    _show_password_error(qtbot, window)
    window.login_view.email_input.setText("other@example.com")
    assert not window.login_view.error_label.isHidden()


def test_the_error_comes_back_on_the_next_failed_submit(qtbot: QtBot, window: MainWindow) -> None:
    _show_password_error(qtbot, window)
    qtbot.keyClicks(window.login_view.email_input, "x")
    window.login_view.submit_sign_in()
    assert not window.login_view.error_label.isHidden()


# ---------------------------------------------------- 5. capped form width


def test_the_form_stays_narrow_and_centred_on_a_wide_window(
    qtbot: QtBot, window: MainWindow
) -> None:
    window.resize(1600, 900)
    qtbot.wait(50)
    view = window.login_view

    assert view.email_input.width() <= MAX_FORM_WIDTH
    assert view.sign_in_button.width() <= MAX_FORM_WIDTH
    left = view.sign_in_button.mapTo(view, view.sign_in_button.rect().topLeft()).x()
    right_gap = view.width() - (left + view.sign_in_button.width())
    assert abs(left - right_gap) <= 2  # centred


def test_the_form_still_fills_a_narrow_window(qtbot: QtBot, window: MainWindow) -> None:
    window.resize(360, 420)
    qtbot.wait(50)
    assert window.login_view.sign_in_button.width() >= 300


# ------------------------------------------------------ 6. length limits


def test_the_message_box_stops_at_the_server_limit(qtbot: QtBot, window: MainWindow) -> None:
    window._show_home(_fake_session())
    box = window.home_view.message_input
    assert box.maxLength() == MAX_CONTENT_LENGTH
    box.setText("x" * (MAX_CONTENT_LENGTH + 50))
    assert len(box.text()) == MAX_CONTENT_LENGTH


def test_name_and_email_fields_stop_at_the_server_limits(window: MainWindow) -> None:
    view = window.login_view
    assert view.name_input.maxLength() == MAX_NAME_LENGTH
    assert view.email_input.maxLength() == MAX_EMAIL_LENGTH
    assert view.register_email_input.maxLength() == MAX_EMAIL_LENGTH


def test_password_fields_are_not_silently_truncated(window: MainWindow) -> None:
    """Cutting a pasted password short would leave the user not knowing their
    real password; over-long passwords get an error message instead.
    """
    view = window.login_view
    for field in (view.password_input, view.register_password_input, view.confirm_input):
        assert field.maxLength() > 10_000
