"""Client tests run headless - no real display is needed to exercise Qt widget logic."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QObject, Signal

from server.tls import ensure_server_cert

# A real (but throwaway) self-signed cert, generated once for the whole test run -
# ssl.create_default_context(cadata=...) parses its input eagerly, so a plain
# placeholder string would raise at ApiClient construction time, not just fail to
# validate anything meaningfully.
_cert_dir = Path(tempfile.mkdtemp(prefix="kairos-test-cert-"))
ensure_server_cert(_cert_dir / "cert.pem", _cert_dir / "key.pem")
_FAKE_CERT_PEM = (_cert_dir / "cert.pem").read_text()


@pytest.fixture(autouse=True)
def _stub_cert_pinning_fetch(monkeypatch):
    """Connecting to a never-before-seen KnownServer triggers a real
    ssl.get_server_certificate() call (see ConnectWindow._connect_to_server) -
    stub it everywhere in tests so a fake test IP (e.g. 192.168.1.10) can't cause
    a real multi-second connection-timeout stall."""
    monkeypatch.setattr(
        "client.views.connect_window.fetch_server_cert_pem",
        lambda host, port: _FAKE_CERT_PEM,
    )


class StubDiscoveryListener(QObject):
    """A no-op stand-in for client.net.DiscoveryListener - duck-types the same
    interface (start/stop/known_servers + the two signals) without ever opening a
    real UDP socket, so constructing a ConnectWindow in tests can't leak onto the
    real network or collide with a real listener/announcer running on the same
    dev machine.
    """

    server_discovered = Signal(object)
    server_lost = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._servers: list[object] = []

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def known_servers(self) -> list[object]:
        return list(self._servers)
