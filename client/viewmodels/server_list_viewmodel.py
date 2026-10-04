import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from PySide6.QtCore import QSettings


@dataclass
class KnownServer:
    id: str
    host: str
    port: int
    nickname: str | None = None
    display_name_cache: str | None = None
    last_connected_at: str | None = None
    # The server's TLS certificate, pinned the first time this server was connected
    # to (trust-on-first-use - see client/net/cert_pinning.py and server/tls.py).
    # None only momentarily, between adding the entry and that first connection.
    cert_pem: str | None = None

    @property
    def base_url(self) -> str:
        return f"https://{self.host}:{self.port}"

    @property
    def label(self) -> str:
        """What to show on the picker button - a user-given nickname wins, then
        the server's own self-reported name, then a bare host:port as a last resort.
        """
        return self.nickname or self.display_name_cache or f"{self.host}:{self.port}"


class ServerListViewModel:
    """Persists the client's list of known Kairos servers via QSettings, so the
    user picks a saved server (by name) instead of retyping a host:port every
    session. Pass an explicit `settings` (e.g. an ini-backed QSettings pointed at
    a temp file) in tests to avoid touching the real user's saved server list.
    """

    _ARRAY_KEY = "known_servers"
    _LAST_USED_KEY = "last_used_server_id"

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings or QSettings("Kairos", "KairosClient")

    def list_servers(self) -> list[KnownServer]:
        servers: list[KnownServer] = []
        count = self._settings.beginReadArray(self._ARRAY_KEY)
        for i in range(count):
            self._settings.setArrayIndex(i)
            servers.append(
                KnownServer(
                    id=self._settings.value("id", ""),
                    host=self._settings.value("host", ""),
                    port=int(self._settings.value("port", 0)),
                    nickname=self._settings.value("nickname", "") or None,
                    display_name_cache=self._settings.value("display_name_cache", "") or None,
                    last_connected_at=self._settings.value("last_connected_at", "") or None,
                    cert_pem=self._settings.value("cert_pem", "") or None,
                )
            )
        self._settings.endArray()
        return servers

    def _save_all(self, servers: list[KnownServer]) -> None:
        self._settings.beginWriteArray(self._ARRAY_KEY)
        for i, server in enumerate(servers):
            self._settings.setArrayIndex(i)
            self._settings.setValue("id", server.id)
            self._settings.setValue("host", server.host)
            self._settings.setValue("port", server.port)
            self._settings.setValue("nickname", server.nickname or "")
            self._settings.setValue("display_name_cache", server.display_name_cache or "")
            self._settings.setValue("last_connected_at", server.last_connected_at or "")
            self._settings.setValue("cert_pem", server.cert_pem or "")
        self._settings.endArray()

    def add_server(
        self,
        host: str,
        port: int,
        display_name_cache: str | None = None,
        nickname: str | None = None,
    ) -> KnownServer:
        servers = self.list_servers()
        new_server = KnownServer(
            id=uuid.uuid4().hex[:8],
            host=host,
            port=port,
            nickname=nickname,
            display_name_cache=display_name_cache,
        )
        servers.append(new_server)
        self._save_all(servers)
        return new_server

    def remove_server(self, server_id: str) -> None:
        servers = [s for s in self.list_servers() if s.id != server_id]
        self._save_all(servers)
        if self.get_last_used_id() == server_id:
            self.set_last_used_id(None)

    def update_display_name_cache(self, server_id: str, display_name: str) -> None:
        servers = self.list_servers()
        for server in servers:
            if server.id == server_id:
                server.display_name_cache = display_name
        self._save_all(servers)

    def update_cert_pem(self, server_id: str, cert_pem: str) -> None:
        servers = self.list_servers()
        for server in servers:
            if server.id == server_id:
                server.cert_pem = cert_pem
        self._save_all(servers)

    def mark_connected(self, server_id: str) -> None:
        servers = self.list_servers()
        now = datetime.now(UTC).isoformat()
        for server in servers:
            if server.id == server_id:
                server.last_connected_at = now
        self._save_all(servers)
        self.set_last_used_id(server_id)

    def get_last_used_id(self) -> str | None:
        return self._settings.value(self._LAST_USED_KEY, "") or None

    def set_last_used_id(self, server_id: str | None) -> None:
        self._settings.setValue(self._LAST_USED_KEY, server_id or "")
