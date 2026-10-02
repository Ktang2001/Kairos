"""App-wide reactions to the state of the connection (context.md goal #3).

``ApiClient`` reports two things after requests, possibly from a background
thread: whether the host could be reached, and whether the session was
refused (expired, revoked, or signed out elsewhere). This object turns those
reports into Qt signals that are delivered on the main thread, so one banner
and one "please sign in again" can serve every screen instead of each screen
showing its own copy of the same error.
"""

from PySide6.QtCore import QObject, Signal

from client.api_client import ApiClient


class SessionEvents(QObject):
    #: True when the host answered, False when it could not be reached.
    #: Only emitted when the state *changes*, so the banner doesn't flicker.
    connection_changed = Signal(bool)
    #: The server no longer accepts this session's token.
    expired = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._reachable = True
        self._expired = False

    def attach(self, client: ApiClient) -> None:
        client.on_connection_changed = self._report_connection
        client.on_session_expired = self._report_expired

    def detach(self, client: ApiClient) -> None:
        client.on_connection_changed = None
        client.on_session_expired = None

    @property
    def reachable(self) -> bool:
        return self._reachable

    # These run on whichever thread made the request. Emitting a signal from
    # there is safe: receivers that are slots of main-thread objects are
    # called later, on the main thread.

    def _report_connection(self, reachable: bool) -> None:
        if reachable != self._reachable:
            self._reachable = reachable
            self._emit(self.connection_changed, reachable)

    def _report_expired(self) -> None:
        if not self._expired:  # several requests may fail at once; react once
            self._expired = True
            self._emit(self.expired)

    @staticmethod
    def _emit(signal, *args) -> None:
        try:
            signal.emit(*args)
        except RuntimeError:  # the signed-in screen has already closed
            pass
