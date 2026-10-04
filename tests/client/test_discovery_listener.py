from time import monotonic

from client.net.discovery_listener import DiscoveryListener
from shared.discovery import encode_announcement


def test_handle_datagram_emits_server_discovered(qtbot):
    listener = DiscoveryListener()
    packet = encode_announcement("inst-1", "Kairos Server", 8000)

    with qtbot.waitSignal(listener.server_discovered, timeout=1000) as blocker:
        listener._handle_datagram(packet, "192.168.1.10")

    discovered = blocker.args[0]
    assert discovered.instance_id == "inst-1"
    assert discovered.name == "Kairos Server"
    assert discovered.host == "192.168.1.10"
    assert discovered.port == 8000


def test_repeated_announces_update_in_place_without_reemitting(qtbot):
    listener = DiscoveryListener()
    seen = []
    listener.server_discovered.connect(lambda s: seen.append(s))

    listener._handle_datagram(encode_announcement("inst-1", "Name A", 8000), "192.168.1.10")
    listener._handle_datagram(encode_announcement("inst-1", "Name B", 8000), "192.168.1.10")

    assert len(seen) == 1  # only the first announce triggers "discovered"
    assert listener.known_servers()[0].name == "Name B"  # but the record is updated


def test_malformed_datagram_is_ignored(qtbot):
    listener = DiscoveryListener()
    seen = []
    listener.server_discovered.connect(lambda s: seen.append(s))

    listener._handle_datagram(b"not a valid packet", "192.168.1.10")

    assert seen == []
    assert listener.known_servers() == []


def test_stale_entry_is_swept_and_emits_server_lost(qtbot):
    listener = DiscoveryListener()
    listener._handle_datagram(encode_announcement("inst-1", "Kairos Server", 8000), "192.168.1.10")
    listener.known_servers()[0].last_seen_at = monotonic() - 100  # force staleness

    with qtbot.waitSignal(listener.server_lost, timeout=1000) as blocker:
        listener._sweep_stale()

    assert blocker.args == ["inst-1"]
    assert listener.known_servers() == []


def test_fresh_entry_is_not_swept(qtbot):
    listener = DiscoveryListener()
    listener._handle_datagram(encode_announcement("inst-1", "Kairos Server", 8000), "192.168.1.10")

    listener._sweep_stale()

    assert len(listener.known_servers()) == 1


def test_stop_clears_known_servers(qtbot):
    listener = DiscoveryListener()
    listener._handle_datagram(encode_announcement("inst-1", "Kairos Server", 8000), "192.168.1.10")

    listener.stop()

    assert listener.known_servers() == []
