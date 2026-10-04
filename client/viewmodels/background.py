"""Run a blocking call (a network request) off the UI thread.

Qt widgets may only be touched from the main thread, so the rule here is:
the *call* runs on a background thread, and its result is handed to the main
thread, where ``on_success``/``on_error`` run and may safely update widgets.

How, and why it is built this way:

* Each call runs on a plain Python thread. No Qt object is created, used or
  destroyed on that thread.
* Results travel through one ``_Dispatcher``: a single QObject created on the
  main thread and never deleted. A signal emitted from another thread to a
  slot of a main-thread object is queued, so the slot runs on the main thread.
* Everything Qt-related about a job (its callbacks, the runner that asked) is
  kept in ``_jobs`` on the main thread, and the worker drops its own reference
  to the call before reporting back. So the last reference to any Qt object
  -- e.g. a view model captured by the call -- is always released on the main
  thread.

An earlier version created a QRunnable, a signals QObject and a relay QObject
per request, whose lifetimes were split between Qt and Python's garbage
collector. Now and then one was destroyed on the wrong thread, or while the
other thread was using it, and the app crashed with an access violation.

(Connecting a worker's signal straight to a plain function or lambda would not
be safe either: PySide6 can then run the function on the worker thread.)
"""

import itertools
import threading
import time
from collections.abc import Callable
from typing import Any

import shiboken6
from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

from client.api_client import ApiError


class _Dispatcher(QObject):
    """Lives on the main thread for the life of the app; never deleted."""

    #: (job id, succeeded, result or error message), emitted from a worker.
    finished = Signal(int, bool, object)

    def __init__(self) -> None:
        super().__init__()
        self.finished.connect(self._deliver)

    @Slot(int, bool, object)
    def _deliver(self, job_id: int, succeeded: bool, value: Any) -> None:
        job = _jobs.pop(job_id, None)
        if job is None:
            return
        runner, _fn, on_success, on_error = job
        # The runner is deleted with the screen that owns it (e.g. signing out
        # while the team list is still loading). Nobody is waiting any more.
        if not shiboken6.isValid(runner):
            return
        (on_success if succeeded else on_error)(value)
        # ``job`` -- and with it the call and anything it captured -- is
        # released here, on the main thread.


_dispatcher: _Dispatcher | None = None

#: job id -> (runner, call, on_success, on_error). Main thread only.
_jobs: dict[int, tuple] = {}
_job_ids = itertools.count(1)

#: Worker threads still running, for ``wait_until_idle``.
_workers: set[threading.Thread] = set()
_workers_lock = threading.Lock()


def _work(job_id: int, box: list) -> None:
    """Runs on the worker thread."""
    fn = box.pop()  # the thread object itself holds no reference to the call
    try:
        outcome = (True, fn())
    except ApiError as exc:
        outcome = (False, exc.message)
    except Exception as exc:  # noqa: BLE001 - must never escape a worker thread
        # An exception escaping a worker thread is printed and lost, leaving
        # the form stuck on "Signing in...". Report it like any failure.
        outcome = (False, f"Something went wrong: {exc}")
    # ``_jobs`` still holds the call, so this is never the last reference.
    del fn
    try:
        if _dispatcher is not None:
            _dispatcher.finished.emit(job_id, *outcome)
    except RuntimeError:  # the app is shutting down
        pass
    finally:
        with _workers_lock:
            _workers.discard(threading.current_thread())


class BackgroundRunner(QObject):
    """Starts background calls for the object that owns it.

    Must be created on the main thread. When it is deleted (with its owner),
    results of calls it started are dropped instead of delivered.
    """

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        global _dispatcher
        if _dispatcher is None:
            _dispatcher = _Dispatcher()

    def run(
        self,
        fn: Callable[[], Any],
        on_success: Callable[[Any], None],
        on_error: Callable[[str], None],
    ) -> None:
        job_id = next(_job_ids)
        _jobs[job_id] = (self, fn, on_success, on_error)
        # Daemon: a request still waiting on a dead host must not keep the
        # app from closing.
        worker = threading.Thread(
            target=_work, args=(job_id, [fn]), name=f"kairos-request-{job_id}", daemon=True
        )
        with _workers_lock:
            _workers.add(worker)
        worker.start()


def wait_until_idle(timeout: float = 10.0) -> bool:
    """Wait for every background call to finish and its result to be
    delivered. Returns False if that took longer than ``timeout`` seconds.

    For tests, so no request outlives the test that started it.
    """
    deadline = time.monotonic() + timeout
    while True:
        with _workers_lock:
            running = list(_workers)
        for worker in running:
            worker.join(max(0.0, deadline - time.monotonic()))
        if QCoreApplication.instance() is not None:
            QCoreApplication.processEvents()  # deliver the queued results
        with _workers_lock:
            idle = not _workers
        if idle and not _jobs:
            return True
        if time.monotonic() > deadline:
            return False
