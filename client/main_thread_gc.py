"""Run Python's garbage collector on the main thread only.

Python's cyclic garbage collector runs on whichever thread happens to
allocate when a collection is due -- in this app, often a background request
thread. If the garbage includes a Qt object Python owns (a closed screen, a
view model, a timer), it is destroyed right there, on the wrong thread, and
Qt crashes now and then with an access violation. Qt objects may only be
destroyed on the thread they belong to.

The usual fix for PySide/PyQt apps, used here: switch off automatic
collection and collect from a timer on the main thread instead. Plain
reference counting still frees almost everything immediately; only objects
caught in reference cycles wait (at most ``INTERVAL_MS``) for the timer.

MERGE-CRITICAL: client/main.py must create one of these before opening any
window, and tests/client/conftest.py does the same for each test. Guarded
by: tests/client/test_main_thread_gc.py.
"""

import gc

from PySide6.QtCore import QObject, QTimer, Slot

#: How often to check whether a collection is due.
INTERVAL_MS = 1000


class MainThreadGarbageCollector(QObject):
    """Must be created on the main thread; collects there while it lives."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._threshold = gc.get_threshold()[0]
        gc.disable()
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVAL_MS)
        self._timer.timeout.connect(self.collect_if_due)
        self._timer.start()

    @Slot()
    def collect_if_due(self) -> None:
        """Called by the timer: collect if Python would have by now."""
        # The same trigger Python's automatic collection would have used.
        if gc.get_count()[0] > self._threshold:
            gc.collect()

    def stop(self) -> None:
        """Hand collection back to Python (for tests)."""
        self._timer.stop()
        gc.enable()
