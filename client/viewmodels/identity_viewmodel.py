from PySide6.QtCore import QSettings


class IdentityViewModel:
    """Holds this session's "who am I" identity - a real login session token (see
    server/api/dependencies.py) plus display info - and remembers the last-used
    identity per server via QSettings, so reconnecting to a server you've used
    before doesn't require re-signing-in every launch.
    """

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings("Kairos", "KairosClient")
        self.user_id: int | None = None
        self.user_name: str | None = None
        self.token: str | None = None

    def _id_key(self, server_id: str) -> str:
        return f"identity/{server_id}/user_id"

    def _name_key(self, server_id: str) -> str:
        return f"identity/{server_id}/user_name"

    def _token_key(self, server_id: str) -> str:
        return f"identity/{server_id}/token"

    def set_identity(self, server_id: str, user_id: int, user_name: str, token: str) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self.token = token
        self._settings.setValue(self._id_key(server_id), user_id)
        self._settings.setValue(self._name_key(server_id), user_name)
        self._settings.setValue(self._token_key(server_id), token)

    def load_cached_identity(self, server_id: str) -> tuple[int, str, str] | None:
        raw_id = self._settings.value(self._id_key(server_id), "")
        name = self._settings.value(self._name_key(server_id), "")
        token = self._settings.value(self._token_key(server_id), "")
        if raw_id == "" or not name or not token:
            return None
        user_id = int(raw_id)
        self.user_id = user_id
        self.user_name = name
        self.token = token
        return user_id, name, token

    def clear(self, server_id: str | None = None) -> None:
        """Drops the in-memory identity; also erases the cached token for
        `server_id` (used on logout/switch-account, so a stale token already
        invalidated server-side isn't offered for silent reconnect next time)."""
        self.user_id = None
        self.user_name = None
        self.token = None
        if server_id is not None:
            self._settings.remove(f"identity/{server_id}")
