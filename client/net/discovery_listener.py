from dataclasses import dataclass, field
from time import monotonic

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QHostAddress, QUdpSocket

from shared.discovery import DISCOVERY_UDP_PORT, STALE_TIMEOUT_MS, decode_announcement

SWEEP_INTERVAL_MS = 1000


@dataclass
class DiscoveredServer:
    instance_id: str
    name: str
    host: str
    port: int
    last_seen_at: float = field(default_factory=monotonic)


def normalize_host(address: QHostAddress) -> str:
    """Collapse an IPv4-mapped-IPv6 sender address (::ffff:192.168.1.5) down to
    plain IPv4 (192.168.1.5) - some platform/socket-stack combinations report the
    mapped form, and a client's saved/connected server list should stay consistent
    either way."""
    ipv4 = address.toIPv4Address()
    if ipv4:
        return QHostAddress(ipv4).toString()
    return address.toString()


class DiscoveryListener(QObject):
    """Listens for DiscoveryAnnouncer broadcasts (server/discovery_announcer.py)
    and tracks which servers are currently live on the LAN.

    Entries are deduped/updated by `instance_id` (not host:port, which can shift
    transiently), and the source host is taken from the datagram's sender address,
    never the payload - not spoofable by a misbehaving sender. A server that stops
    announcing (host went offline) is swept out after STALE_TIMEOUT_MS.
    """

    server_discovered = Signal(object)  # DiscoveredServer
    server_lost = Signal(str)  # instance_id

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._socket: QUdpSocket | None = None
        self._sweep_timer: QTimer | None = None
        self._servers: dict[str, DiscoveredServer] = {}

    def start(self) -> None:
        if self._socket is not None:
            return  # already running

        self._socket = QUdpSocket(self)
        self._socket.bind(
            QHostAddress.SpecialAddress.AnyIPv4,
            DISCOVERY_UDP_PORT,
            QUdpSocket.BindFlag.ShareAddress | QUdpSocket.BindFlag.ReuseAddressHint,
        )
        self._socket.readyRead.connect(self._on_ready_read)

        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(SWEEP_INTERVAL_MS)
        self._sweep_timer.timeout.connect(self._sweep_stale)
        self._sweep_timer.start()

    def stop(self) -> None:
        if self._sweep_timer is not None:
            self._sweep_timer.stop()
            self._sweep_timer = None
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        self._servers.clear()

    def known_servers(self) -> list[DiscoveredServer]:
        return list(self._servers.values())

    def _on_ready_read(self) -> None:
        while self._socket is not None and self._socket.hasPendingDatagrams():
            datagram = self._socket.receiveDatagram()
            host = normalize_host(datagram.senderAddress())
            self._handle_datagram(bytes(datagram.data()), host)

    def _handle_datagram(self, data: bytes, host: str) -> None:
        """Exposed directly (bypassing the real socket) so tests can feed
        synthetic datagrams without opening a real UDP port."""
        announcement = decode_announcement(data)
        if announcement is None:
            return
        self._upsert(announcement.instance_id, announcement.name, host, announcement.port)

    def _upsert(self, instance_id: str, name: str, host: str, port: int) -> None:
        is_new = instance_id not in self._servers
        self._servers[instance_id] = DiscoveredServer(
            instance_id=instance_id, name=name, host=host, port=port, last_seen_at=monotonic()
        )
        if is_new:
            self.server_discovered.emit(self._servers[instance_id])

    def _sweep_stale(self) -> None:
        now = monotonic()
        stale_ids = [
            instance_id
            for instance_id, server in self._servers.items()
            if (now - server.last_seen_at) * 1000 > STALE_TIMEOUT_MS
        ]
        for instance_id in stale_ids:
            del self._servers[instance_id]
            self.server_lost.emit(instance_id)
