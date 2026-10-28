"""The Dashboard's data (context.md goal #7), without any widgets.

One request, GET /dashboard, on a background thread; the page shows whatever
came back. Refreshed when the page is opened and on the app's timer.
"""

from PySide6.QtCore import QObject, Signal

from client.viewmodels.background import BackgroundRunner
from client.viewmodels.session import Session


class DashboardViewModel(QObject):
    """Loads the dashboard figures for the signed-in user."""

    #: The /dashboard response (server/schemas/dashboard.py).
    loaded = Signal(dict)
    busy_changed = Signal(bool)
    #: The message to show, or "" to clear it.
    error_changed = Signal(str)

    def __init__(
        self,
        session: Session,
        runner: BackgroundRunner | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self._runner = runner or BackgroundRunner(self)
        self._busy = False
        #: The last figures loaded, or None before the first load.
        self.data: dict | None = None

    @property
    def busy(self) -> bool:
        """True while the request is in flight."""
        return self._busy

    def refresh(self) -> None:
        """Reload the figures (ignored while a load is already running)."""
        if self._busy:
            return
        client = self.session.client
        self._set_busy(True)
        self._runner.run(client.get_dashboard, on_success=self._loaded, on_error=self._failed)

    def _loaded(self, data: dict) -> None:
        """Main thread: keep the figures and tell the page."""
        self._set_busy(False)
        self.data = data
        self.error_changed.emit("")
        self.loaded.emit(data)

    def _failed(self, message: str) -> None:
        """Main thread: say why the figures could not be loaded."""
        self._set_busy(False)
        self.error_changed.emit(message)

    def _set_busy(self, busy: bool) -> None:
        """Record whether the request is in flight and tell the page."""
        self._busy = busy
        self.busy_changed.emit(busy)
