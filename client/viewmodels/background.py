"""Run a blocking call (a network request) off the UI thread.

Qt widgets may only be touched from the main thread, so the rule here is:
the *call* runs on a pool thread, and its result is delivered to a slot on a
``QObject`` that lives on the main thread. Because sender and receiver are on
different threads, Qt queues the delivery, so ``on_success``/``on_error``
always run on the main thread and may safely update widgets.

(Connecting the worker's signal straight to a plain function or lambda would
not be safe: PySide6 can then run the function on the worker thread.)
"""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from client.api_client import ApiError


class _Signals(QObject):
    """Emitted from the pool thread."""

    succeeded = Signal(object)
    failed = Signal(str)


class _Relay(QObject):
    """Lives on the main thread; its slots run the caller's callbacks there."""

    def __init__(
        self,
        on_success: Callable[[Any], None],
        on_error: Callable[[str], None],
        on_finished: Callable[["_Relay"], None],
        parent: QObject,
    ) -> None:
        super().__init__(parent)
        self._on_success = on_success
        self._on_error = on_error
        self._on_finished = on_finished

    @Slot(object)
    def deliver_success(self, result: Any) -> None:
        try:
            self._on_success(result)
        finally:
            self._on_finished(self)

    @Slot(str)
    def deliver_error(self, message: str) -> None:
        try:
            self._on_error(message)
        finally:
            self._on_finished(self)


class _Job(QRunnable):
    def __init__(self, fn: Callable[[], Any], signals: _Signals) -> None:
        super().__init__()
        self._fn = fn
        self._signals = signals

    def run(self) -> None:
        try:
            result = self._fn()
        except ApiError as exc:
            self._signals.failed.emit(exc.message)
        except Exception as exc:  # noqa: BLE001 - must never escape a pool thread
            # An exception escaping a pool thread is printed and lost, leaving
            # the form stuck on "Signing in...". Report it like any failure.
            self._signals.failed.emit(f"Something went wrong: {exc}")
        else:
            self._signals.succeeded.emit(result)


class BackgroundRunner(QObject):
    """Starts jobs and keeps their signal/relay objects alive until they finish.

    Must be created on the main thread.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: dict[_Relay, _Signals] = {}

    def run(
        self,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[str], None],
    ) -> None:
        relay = _Relay(on_success, on_error, self._finished, parent=self)
        # No parent: the signals object is only ever emitted from the pool
        # thread and is kept alive by ``_pending`` until the relay is done.
        signals = _Signals()
        signals.succeeded.connect(relay.deliver_success)
        signals.failed.connect(relay.deliver_error)
        self._pending[relay] = signals

        QThreadPool.globalInstance().start(_Job(fn, signals))

    def _finished(self, relay: _Relay) -> None:
        self._pending.pop(relay, None)
        relay.deleteLater()

    @property
    def busy(self) -> bool:
        return bool(self._pending)
