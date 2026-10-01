"""What the client remembers between launches: the server address and the
last email used to sign in. Nothing else -- in particular never the password
or the session token, so a shared computer does not leave anyone signed in.

Backed by ``QSettings``, which picks the right place per platform (the
registry on Windows, ``~/.config`` on Linux), so no paths are hardcoded.
"""

from PySide6.QtCore import QSettings

ORGANIZATION = "Technical Difficulties"
APPLICATION = "Kairos"

_SERVER_URL = "connection/server_url"
_LAST_EMAIL = "account/last_email"


class ClientSettings:
    def __init__(self, store: QSettings | None = None) -> None:
        # Tests pass an INI-file store in a temp directory instead of the real one.
        self._store = store if store is not None else QSettings(ORGANIZATION, APPLICATION)

    @property
    def server_url(self) -> str | None:
        return self._store.value(_SERVER_URL, None, type=str) or None

    @server_url.setter
    def server_url(self, value: str) -> None:
        self._store.setValue(_SERVER_URL, value)
        self._store.sync()

    @property
    def last_email(self) -> str | None:
        return self._store.value(_LAST_EMAIL, None, type=str) or None

    @last_email.setter
    def last_email(self, value: str) -> None:
        self._store.setValue(_LAST_EMAIL, value)
        self._store.sync()
