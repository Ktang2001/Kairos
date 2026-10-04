"""Tests for client/viewmodels/background.py: running requests off the UI
thread and handing their results back to it.

The last tests guard against the access violations an earlier design
caused: Qt objects destroyed on a worker thread, or by the garbage collector
while a worker was still using them.
"""

import gc
import threading
from typing import ClassVar

import pytest
import shiboken6
from PySide6.QtCore import QObject
from pytestqt.qtbot import QtBot

from client.api_client import ApiError
from client.viewmodels.background import BackgroundRunner, wait_until_idle

WAIT_MS = 5000


class Results:
    def __init__(self) -> None:
        self.successes: list = []
        self.errors: list[str] = []
        self.threads: list[str] = []

    def success(self, value) -> None:
        self.threads.append(threading.current_thread().name)
        self.successes.append(value)

    def error(self, message: str) -> None:
        self.threads.append(threading.current_thread().name)
        self.errors.append(message)

    @property
    def count(self) -> int:
        return len(self.successes) + len(self.errors)


@pytest.fixture
def results() -> Results:
    return Results()


def test_the_call_runs_off_the_main_thread_and_the_result_arrives_on_it(
    qtbot: QtBot, results: Results
) -> None:
    ran_on: list[str] = []

    def call() -> int:
        ran_on.append(threading.current_thread().name)
        return 42

    BackgroundRunner().run(call, results.success, results.error)
    qtbot.waitUntil(lambda: results.count == 1, timeout=WAIT_MS)

    assert results.successes == [42]
    assert ran_on != ["MainThread"]
    assert results.threads == ["MainThread"]


def test_an_api_error_arrives_as_its_message(qtbot: QtBot, results: Results) -> None:
    def call():
        raise ApiError("Incorrect email or password", 401)

    BackgroundRunner().run(call, results.success, results.error)
    qtbot.waitUntil(lambda: results.count == 1, timeout=WAIT_MS)
    assert results.errors == ["Incorrect email or password"]


def test_an_unexpected_error_is_reported_not_lost(qtbot: QtBot, results: Results) -> None:
    def call():
        raise ValueError("boom")

    BackgroundRunner().run(call, results.success, results.error)
    qtbot.waitUntil(lambda: results.count == 1, timeout=WAIT_MS)
    assert results.errors == ["Something went wrong: boom"]


def test_results_for_a_closed_screen_are_dropped(qtbot: QtBot, results: Results) -> None:
    gate = threading.Event()
    owner = QObject()
    BackgroundRunner(owner).run(lambda: gate.wait(5), results.success, results.error)

    owner.deleteLater()  # e.g. signed out while the request was running
    qtbot.waitUntil(lambda: not _alive(owner), timeout=WAIT_MS)
    gate.set()
    assert wait_until_idle(5)
    assert results.count == 0


def _alive(obj: QObject) -> bool:
    return shiboken6.isValid(obj)


def test_wait_until_idle_reports_a_call_that_is_still_running(results: Results) -> None:
    gate = threading.Event()
    BackgroundRunner().run(lambda: gate.wait(5), results.success, results.error)
    try:
        assert wait_until_idle(0.2) is False
    finally:
        gate.set()
    assert wait_until_idle(5) is True
    assert results.count == 1


# ------------------------------------------------- thread-safety guards


class Captured:
    """Records which thread released the last reference to it."""

    released_on: ClassVar[list[str]] = []

    def __del__(self) -> None:
        Captured.released_on.append(threading.current_thread().name)


def test_whatever_a_call_captures_is_released_on_the_main_thread(results: Results) -> None:
    # If a view model captured by the call were released on the worker
    # thread, Qt would destroy it there -- the crash this design prevents.
    Captured.released_on = []
    for _ in range(20):
        captured = Captured()
        BackgroundRunner().run(lambda c=captured: id(c), results.success, results.error)
        del captured
    assert wait_until_idle(5)
    gc.collect()
    assert len(Captured.released_on) == 20
    assert set(Captured.released_on) == {"MainThread"}


def test_garbage_collection_during_requests_does_not_crash(qtbot: QtBot) -> None:
    # Many short-lived owners (like screens opened and closed) with requests
    # in flight, collected while their workers are still running. The old
    # per-request QObjects crashed here now and then.
    delivered: list[int] = []
    gates = [threading.Event() for _ in range(5)]
    for round_ in range(30):
        owner = QObject()
        runner = BackgroundRunner(owner if round_ % 2 else None)
        gate = gates[round_ % len(gates)]
        runner.run(
            lambda o=owner, g=gate: (g.wait(5), id(o))[1],
            lambda _value: delivered.append(1),
            lambda _message: delivered.append(1),
        )
        del owner, runner
        gc.collect()
        if round_ % 5 == 4:
            gates[(round_ // 5) % len(gates)].set()
        qtbot.wait(1)
    for gate in gates:
        gate.set()
    for _ in range(5):
        gc.collect()
        qtbot.wait(5)
    assert wait_until_idle(5)
    gc.collect()
