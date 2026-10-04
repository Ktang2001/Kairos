"""Client tests run headless - no real display is needed to exercise Qt widget logic."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject, Signal


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
