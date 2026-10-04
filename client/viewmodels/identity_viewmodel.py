from PySide6.QtCore import QSettings


class IdentityViewModel:
    """Holds this session's placeholder "who am I" identity (see
    server/api/dependencies.py - no real login exists yet) and remembers the
    last-used identity per server via QSettings, so reconnecting to a server you've
    used before doesn't require re-picking yourself every launch.
    """

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings("Kairos", "KairosClient")
        self.user_id: int | None = None
        self.user_name: str | None = None

    def _id_key(self, server_id: str) -> str:
        return f"identity/{server_id}/user_id"

    def _name_key(self, server_id: str) -> str:
        return f"identity/{server_id}/user_name"

    def set_identity(self, server_id: str, user_id: int, user_name: str) -> None:
        self.user_id = user_id
        self.user_name = user_name
        self._settings.setValue(self._id_key(server_id), user_id)
        self._settings.setValue(self._name_key(server_id), user_name)

    def load_cached_identity(self, server_id: str) -> tuple[int, str] | None:
        raw_id = self._settings.value(self._id_key(server_id), "")
        name = self._settings.value(self._name_key(server_id), "")
        if raw_id == "" or not name:
            return None
        user_id = int(raw_id)
        self.user_id = user_id
        self.user_name = name
        return user_id, name

    def clear(self) -> None:
        self.user_id = None
        self.user_name = None
