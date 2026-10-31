"""How you like to join meetings and be reminded of them, kept on this
computer (the Profile page).

Kairos can't sign anyone in to Jitsi -- meet.jit.si signs people in with
Google, GitHub or Facebook on its own site, and the browser remembers it --
but it can fill in what Jitsi lets a link set: your name in the call, and
whether you join muted or with your camera off. Those go in the link's
``#fragment``, which the browser keeps to itself (never sent to a server).
"""

import json
from urllib.parse import quote, urlsplit

from PySide6.QtCore import QSettings

from shared.meetings import DEFAULT_REMINDER_MINUTES, PROFILE_REMINDER_CHOICES

_DISPLAY_NAME_KEY = "meetings/display_name"
_START_MUTED_KEY = "meetings/start_muted"
_CAMERA_OFF_KEY = "meetings/camera_off"
_REMINDER_KEY = "meetings/reminder_minutes"
_FIRED_KEY = "meetings/fired_reminders"

#: Stored for "Off" (no default reminder).
_REMINDER_OFF = "off"
#: How many shown reminders are remembered (oldest forgotten first): plenty
#: for months of meetings, small enough to keep the settings file tidy.
MAX_REMEMBERED_REMINDERS = 300

#: The longest name kept; Jitsi itself cuts names much shorter.
MAX_MEETING_NAME_LENGTH = 100


def is_safe_meeting_url(url: str) -> bool:
    """True for an https:// link with a host -- the only kind Kairos opens.

    The server only hands out https links (server_settings_service), but the
    client checks too: a link is opened in the browser, so anything else
    (http://, file://, a custom app scheme) is refused rather than trusted.
    """
    parts = urlsplit(url)
    return parts.scheme == "https" and bool(parts.hostname)


def _settings_bool(settings: QSettings, key: str) -> bool:
    """A yes/no setting; QSettings' INI files hand booleans back as text."""
    value = settings.value(key, False)
    if isinstance(value, str):
        return value.lower() == "true"
    return bool(value)


class MeetingPreferences:
    """Your meeting name and join options, saved in QSettings on this computer."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings("Kairos", "KairosClient")

    @property
    def display_name(self) -> str:
        """Your name in meetings, or "" to use your Kairos name."""
        return str(self._settings.value(_DISPLAY_NAME_KEY, "") or "")

    @display_name.setter
    def display_name(self, name: str) -> None:
        self._settings.setValue(_DISPLAY_NAME_KEY, name.strip()[:MAX_MEETING_NAME_LENGTH])

    @property
    def start_muted(self) -> bool:
        return _settings_bool(self._settings, _START_MUTED_KEY)

    @start_muted.setter
    def start_muted(self, value: bool) -> None:
        self._settings.setValue(_START_MUTED_KEY, bool(value))

    @property
    def camera_off(self) -> bool:
        return _settings_bool(self._settings, _CAMERA_OFF_KEY)

    @camera_off.setter
    def camera_off(self, value: bool) -> None:
        self._settings.setValue(_CAMERA_OFF_KEY, bool(value))

    @property
    def reminder_minutes(self) -> int | None:
        """Your default reminder, in minutes before each meeting; None for Off.

        Anything unexpected in the settings file (edited by hand, or from a
        newer version) reads as the default rather than breaking reminders.
        """
        value = self._settings.value(_REMINDER_KEY, DEFAULT_REMINDER_MINUTES)
        if str(value).lower() == _REMINDER_OFF:
            return None
        try:
            minutes = int(value)
        except (TypeError, ValueError):
            return DEFAULT_REMINDER_MINUTES
        return minutes if minutes in PROFILE_REMINDER_CHOICES else DEFAULT_REMINDER_MINUTES

    @reminder_minutes.setter
    def reminder_minutes(self, minutes: int | None) -> None:
        if minutes is not None and minutes not in PROFILE_REMINDER_CHOICES:
            raise ValueError(f"reminder must be one of {PROFILE_REMINDER_CHOICES} or None")
        self._settings.setValue(_REMINDER_KEY, _REMINDER_OFF if minutes is None else minutes)

    def fired_reminders(self) -> list[str]:
        """Reminders already shown on this computer, oldest first, so restarting
        Kairos or signing in again doesn't show them a second time."""
        value = self._settings.value(_FIRED_KEY, [])
        if isinstance(value, str):  # QSettings hands back a one-item list as a str
            value = [value]
        return [str(key) for key in value or []]

    def remember_fired(self, keys: list[str]) -> None:
        """Add ``keys`` to the shown reminders, keeping the newest ones."""
        known = self.fired_reminders()
        known += [key for key in keys if key not in known]
        self._settings.setValue(_FIRED_KEY, known[-MAX_REMEMBERED_REMINDERS:])

    def join_url(self, url: str, kairos_name: str) -> str:
        """The meeting link with your name and join options added.

        Jitsi reads ``#userInfo.displayName=...&config.startWithAudioMuted=...``:
        each value JSON-encoded, then URL-encoded, so a name with quotes, ``&``
        or ``#`` in it can't break out into another setting.
        """
        name = self.display_name or kairos_name
        options = []
        if name:
            options.append(f"userInfo.displayName={quote(json.dumps(name))}")
        if self.start_muted:
            options.append("config.startWithAudioMuted=true")
        if self.camera_off:
            options.append("config.startWithVideoMuted=true")
        base = url.split("#", 1)[0]
        return f"{base}#{'&'.join(options)}" if options else base
