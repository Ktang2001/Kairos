"""The one real-socket test for discovery - everything else in
test_discovery_listener.py / test_discovery_announcer.py stays fake to avoid
flaky CI. This proves the real QUdpSocket plumbing (bind + broadcast + receive)
actually works end to end on loopback, not just the packet encode/decode logic.
"""

import socket

from PySide6.QtNetwork import QHostAddress

from client.net.discovery_listener import DiscoveryListener
from shared.discovery import DISCOVERY_UDP_PORT, encode_announcement


def test_real_udp_packet_is_received_by_listener(qtbot):
    listener = DiscoveryListener()
    listener.start()

    try:
        packet = encode_announcement("inst-loopback", "Kairos Server", 8000)
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender.sendto(packet, ("127.0.0.1", DISCOVERY_UDP_PORT))
        sender.close()

        with qtbot.waitSignal(listener.server_discovered, timeout=2000) as blocker:
            pass

        discovered = blocker.args[0]
        assert discovered.instance_id == "inst-loopback"
        assert discovered.name == "Kairos Server"
        assert discovered.port == 8000
        # Loopback sender shows up as 127.0.0.1 (or its IPv6 equivalent, normalized).
        assert discovered.host in (
            "127.0.0.1",
            QHostAddress(QHostAddress.SpecialAddress.LocalHost).toString(),
        )
    finally:
        listener.stop()
