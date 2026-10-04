"""Tests for client/main_thread_gc.py.

Python's garbage collector used to run on whichever thread allocated when a
collection was due -- a request thread, or the live test server's -- and
destroy Qt objects there, which crashed now and then (access violations
while "Garbage-collecting"). These pin down that collection happens on the
main thread only.
"""

import gc
import threading
from typing import ClassVar

from PySide6.QtCore import QObject
from pytestqt.qtbot import QtBot

from client.main_thread_gc import INTERVAL_MS, MainThreadGarbageCollector


class Tracked(QObject):
    """A Qt object that records which thread destroyed it."""

    destroyed_on: ClassVar[list[str]] = []

    def __del__(self) -> None:
        Tracked.destroyed_on.append(threading.current_thread().name)


def _cyclic_garbage() -> None:
    obj = Tracked()
    obj.myself = obj  # only the cyclic collector can free this


#: Kept alive until the test ends: freeing objects lowers the count that
#: decides whether a collection is due.
_junk: list = []


def _allocate_a_lot() -> None:
    _junk.append([[] for _ in range(50_000)])  # far past the collection threshold


def test_automatic_collection_is_off_while_it_runs_and_back_afterwards() -> None:
    collector = MainThreadGarbageCollector()
    try:
        assert not gc.isenabled()
    finally:
        collector.stop()
    assert gc.isenabled()


def teardown_function() -> None:
    _junk.clear()


def test_a_worker_thread_never_destroys_qt_objects() -> None:
    Tracked.destroyed_on = []
    collector = MainThreadGarbageCollector()
    try:
        _cyclic_garbage()
        worker = threading.Thread(target=_allocate_a_lot, name="worker")
        worker.start()
        worker.join()
        assert Tracked.destroyed_on == []  # the worker did not collect it

        collector.collect_if_due()
        assert Tracked.destroyed_on == ["MainThread"]
    finally:
        collector.stop()


def test_nothing_is_collected_until_it_is_due() -> None:
    collector = MainThreadGarbageCollector()
    try:
        gc.collect()  # start from a clean count
        Tracked.destroyed_on = []
        _cyclic_garbage()
        collector.collect_if_due()
        assert Tracked.destroyed_on == []  # a handful of objects: not due yet
    finally:
        collector.stop()
        gc.collect()


def test_the_timer_collects_on_its_own(qtbot: QtBot) -> None:
    Tracked.destroyed_on = []
    collector = MainThreadGarbageCollector()
    try:
        _cyclic_garbage()
        _allocate_a_lot()
        qtbot.waitUntil(lambda: Tracked.destroyed_on == ["MainThread"], timeout=INTERVAL_MS * 3)
    finally:
        collector.stop()
