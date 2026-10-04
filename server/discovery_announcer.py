from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtNetwork import QHostAddress, QUdpSocket

from shared.discovery import (
    ANNOUNCE_INTERVAL_MS,
    DISCOVERY_UDP_PORT,
    encode_announcement,
    new_instance_id,
)


class DiscoveryAnnouncer(QObject):
    """Broadcasts this host's presence on the LAN so clients can find it without
    typing an IP address (see shared/discovery.py for the packet format,
    client/net/discovery_listener.py for the client side).

    `get_display_name` is called fresh on every tick (not cached at construction)
    so a live rename via the Server Settings box is picked up by the very next
    announce - same idiom as this window's other per-tick SessionLocal() calls.
    """

    def __init__(
        self,
        get_display_name: Callable[[], str],
        http_port: int,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._get_display_name = get_display_name
        self._http_port = http_port
        self._instance_id = new_instance_id()
        self._socket: QUdpSocket | None = None
        self._timer: QTimer | None = None

    def start(self) -> None:
        if self._socket is not None:
            return  # already running

        self._socket = QUdpSocket(self)
        self._socket.bind(QHostAddress.SpecialAddress.AnyIPv4, 0)

        self._timer = QTimer(self)
        self._timer.setInterval(ANNOUNCE_INTERVAL_MS)
        self._timer.timeout.connect(self._announce)
        self._timer.start()
        self._announce()

    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None

    def _announce(self) -> None:
        if self._socket is None:
            return
        packet = encode_announcement(self._instance_id, self._get_display_name(), self._http_port)
        self._socket.writeDatagram(
            packet, QHostAddress.SpecialAddress.Broadcast, DISCOVERY_UDP_PORT
        )
