"""LAN auto-discovery packet format, shared by the server's announcer
(server/discovery_announcer.py) and the client's listener
(client/net/discovery_listener.py). No Qt imports here - both sides can import
this without pulling in GUI dependencies.
"""

import json
import uuid
from dataclasses import dataclass

DISCOVERY_UDP_PORT = 52312
DISCOVERY_PROTOCOL_VERSION = 1
ANNOUNCE_INTERVAL_MS = 2000
STALE_TIMEOUT_MS = 6000


@dataclass
class DiscoveryAnnouncement:
    instance_id: str
    name: str
    port: int


def new_instance_id() -> str:
    """One id per announcer process start - the dedupe key clients key off of,
    since it (unlike host:port) survives a transient IP change."""
    return uuid.uuid4().hex


def encode_announcement(instance_id: str, name: str, port: int) -> bytes:
    payload = {
        "proto": DISCOVERY_PROTOCOL_VERSION,
        "id": instance_id,
        "name": name,
        "port": port,
    }
    return json.dumps(payload).encode("utf-8")


def decode_announcement(data: bytes) -> DiscoveryAnnouncement | None:
    """Never raises - malformed or foreign UDP traffic on this port just yields
    None rather than crashing the listener."""
    try:
        payload = json.loads(data.decode("utf-8"))
        if payload.get("proto") != DISCOVERY_PROTOCOL_VERSION:
            return None
        instance_id = payload["id"]
        name = payload["name"]
        port = payload["port"]
    except (ValueError, KeyError, UnicodeDecodeError, AttributeError, TypeError):
        return None

    if not isinstance(instance_id, str) or not isinstance(name, str) or not isinstance(port, int):
        return None
    return DiscoveryAnnouncement(instance_id=instance_id, name=name, port=port)
