from PySide6.QtNetwork import QUdpSocket

from server.discovery_announcer import DiscoveryAnnouncer
from shared.discovery import decode_announcement


def test_start_sends_an_immediate_announcement(qtbot, monkeypatch) -> None:
    sent: list[bytes] = []
    monkeypatch.setattr(
        QUdpSocket,
        "writeDatagram",
        lambda self, data, address, port: sent.append(bytes(data)),
    )
    monkeypatch.setattr(QUdpSocket, "bind", lambda self, address, port: True)

    announcer = DiscoveryAnnouncer(get_display_name=lambda: "Kairos Server", http_port=8000)
    announcer.start()

    assert len(sent) == 1
    announcement = decode_announcement(sent[0])
    assert announcement.name == "Kairos Server"
    assert announcement.port == 8000

    announcer.stop()


def test_announce_reflects_current_display_name_each_tick(qtbot, monkeypatch) -> None:
    sent: list[bytes] = []
    monkeypatch.setattr(
        QUdpSocket,
        "writeDatagram",
        lambda self, data, address, port: sent.append(bytes(data)),
    )
    monkeypatch.setattr(QUdpSocket, "bind", lambda self, address, port: True)

    current_name = "Original Name"
    announcer = DiscoveryAnnouncer(get_display_name=lambda: current_name, http_port=8000)
    announcer.start()
    assert decode_announcement(sent[-1]).name == "Original Name"

    current_name = "Renamed Server"
    announcer._announce()

    assert decode_announcement(sent[-1]).name == "Renamed Server"
    announcer.stop()


def test_same_instance_id_across_multiple_announces(qtbot, monkeypatch) -> None:
    sent: list[bytes] = []
    monkeypatch.setattr(
        QUdpSocket,
        "writeDatagram",
        lambda self, data, address, port: sent.append(bytes(data)),
    )
    monkeypatch.setattr(QUdpSocket, "bind", lambda self, address, port: True)

    announcer = DiscoveryAnnouncer(get_display_name=lambda: "Kairos Server", http_port=8000)
    announcer.start()
    announcer._announce()
    announcer._announce()

    ids = {decode_announcement(p).instance_id for p in sent}
    assert len(ids) == 1
    announcer.stop()


def test_stop_prevents_further_announces(qtbot, monkeypatch) -> None:
    sent: list[bytes] = []
    monkeypatch.setattr(
        QUdpSocket,
        "writeDatagram",
        lambda self, data, address, port: sent.append(bytes(data)),
    )
    monkeypatch.setattr(QUdpSocket, "bind", lambda self, address, port: True)

    announcer = DiscoveryAnnouncer(get_display_name=lambda: "Kairos Server", http_port=8000)
    announcer.start()
    announcer.stop()

    count_before = len(sent)
    announcer._announce()  # no-op after stop()

    assert len(sent) == count_before
