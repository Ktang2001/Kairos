"""Tests for client/views/profile_page.py: meeting preferences and Jitsi sign-in."""

from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from pytestqt.qtbot import QtBot

from client.viewmodels.meeting_preferences import MeetingPreferences
from client.viewmodels.meetings_viewmodel import MeetingsViewModel
from client.views.profile_page import ProfilePage


class _FakeClient:
    def get_server_info(self) -> dict:
        return {"display_name": "Kairos", "jitsi_base_url": "https://jitsi.example.org/meet"}


@pytest.fixture
def preferences(tmp_path: Path) -> MeetingPreferences:
    return MeetingPreferences(QSettings(str(tmp_path / "prefs.ini"), QSettings.Format.IniFormat))


@pytest.fixture
def page(qtbot: QtBot, preferences: MeetingPreferences) -> ProfilePage:
    meetings = MeetingsViewModel(_FakeClient(), preferences, display_name="Max")
    meetings.opened = []
    meetings.open_url = lambda url: meetings.opened.append(url) or True
    view = ProfilePage(preferences, meetings, kairos_name="Max")
    qtbot.addWidget(view)
    return view


def test_your_kairos_name_is_the_suggestion(page: ProfilePage) -> None:
    assert page.name_input.text() == ""
    assert page.name_input.placeholderText() == "Max"


def test_changes_are_saved_straight_away(
    page: ProfilePage, preferences: MeetingPreferences
) -> None:
    page.name_input.setText("  Max M.  ")
    page.name_input.editingFinished.emit()
    page.muted_box.setChecked(True)
    page.camera_box.setChecked(True)

    assert preferences.display_name == "Max M."
    assert page.name_input.text() == "Max M."
    assert preferences.start_muted is True
    assert preferences.camera_off is True
    assert "Saved" in page.saved_label.text()


def test_saved_preferences_are_shown_when_the_page_opens(
    qtbot: QtBot, preferences: MeetingPreferences
) -> None:
    preferences.display_name = "Maxine"
    preferences.camera_off = True

    view = ProfilePage(preferences, MeetingsViewModel(_FakeClient(), preferences), kairos_name="")
    qtbot.addWidget(view)

    assert view.name_input.text() == "Maxine"
    assert view.camera_box.isChecked()
    assert not view.muted_box.isChecked()


def test_sign_in_opens_the_servers_jitsi_site(qtbot: QtBot, page: ProfilePage) -> None:
    page.sign_in_button.click()
    qtbot.waitUntil(lambda: bool(page.meetings.opened), timeout=5000)

    assert page.meetings.opened == ["https://jitsi.example.org/meet"]


def test_it_explains_why_kairos_cannot_sign_you_in(page: ProfilePage) -> None:
    assert "Kairos never sees that sign-in" in page.explanation.text()


def test_your_default_reminder_is_saved(page: ProfilePage, preferences: MeetingPreferences) -> None:
    assert page.reminder_input.currentData() == 15

    page.reminder_input.setCurrentIndex(page.reminder_input.findData(None))
    assert preferences.reminder_minutes is None

    page.reminder_input.setCurrentIndex(page.reminder_input.findData(60))
    assert preferences.reminder_minutes == 60
    assert page.reminder_input.currentText() == "1 hour before"
