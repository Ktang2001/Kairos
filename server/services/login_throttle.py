"""Slows down password guessing on POST /auth/login.

Two counters of recent failed logins, kept in memory:

* per (email, client address): after ``FAILURES_BEFORE_LOCK`` wrong passwords
  that pair is locked for ``FIRST_LOCK_SECONDS``, doubling with each further
  failure up to ``MAX_LOCK_SECONDS``. Keyed on the *pair*, not the email
  alone, so someone guessing from their own computer cannot lock the real
  owner out of their account on theirs.
* per client address: ``FAILURES_BEFORE_ADDRESS_LOCK`` failures across *any*
  emails locks that address the same way, which stops one machine spraying
  a common password at every account.

A locked attempt is refused before the password is checked, so it costs the
host no scrypt work -- the lock is also a defence against using login as a
CPU/memory exhaustion attack. A successful login clears the pair's counter.

In memory on purpose: the backend is one process on one of the team's
computers (context.md), so there is nothing to share state with, and a
restart clearing the counters is acceptable.
"""

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

FAILURES_BEFORE_LOCK = 5
FAILURES_BEFORE_ADDRESS_LOCK = 20
FIRST_LOCK_SECONDS = 60
MAX_LOCK_SECONDS = 15 * 60

#: Counters untouched for this long are forgotten, so the table cannot grow
#: without bound from one-off typos.
FORGET_AFTER_SECONDS = 60 * 60
#: Prune at most this often.
PRUNE_EVERY_SECONDS = 60


@dataclass
class _Counter:
    """Failed attempts for one key (an email+address pair, or an address), and until when it is
    locked.
    """

    failures: int = 0
    locked_until: float = 0.0
    last_seen: float = 0.0


def lock_seconds(failures: int, threshold: int) -> float:
    """How long ``failures`` failures lock for: 0 below the threshold, then
    FIRST_LOCK_SECONDS doubling per extra failure, capped at MAX_LOCK_SECONDS.
    """
    if failures < threshold:
        return 0.0
    return float(min(FIRST_LOCK_SECONDS * 2 ** (failures - threshold), MAX_LOCK_SECONDS))


class LoginThrottle:
    """The in-memory lockout used by POST /auth/login (one per app, on ``app.state``). Safe to use
    from several request threads at once.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        # The clock is injectable so tests can move time forward instantly.
        self._clock = clock
        self._lock = threading.Lock()  # sync routes run on a thread pool
        self._pairs: dict[tuple[str, str], _Counter] = {}
        self._addresses: dict[str, _Counter] = {}
        self._last_prune = 0.0

    def retry_after(self, email: str, address: str) -> int:
        """Seconds until this pair may try again; 0 if it may try now."""
        now = self._clock()
        with self._lock:
            waits = [
                counter.locked_until - now
                for counter in (
                    self._pairs.get(self._pair_key(email, address)),
                    self._addresses.get(address),
                )
                if counter is not None
            ]
        wait = max(waits, default=0.0)
        return math.ceil(wait) if wait > 0 else 0

    def record_failure(self, email: str, address: str) -> None:
        """Count a wrong password against both the email+address pair and the address, locking
        either once over its limit.
        """
        now = self._clock()
        with self._lock:
            self._prune(now)
            pair = self._pairs.setdefault(self._pair_key(email, address), _Counter())
            self._bump(pair, now, FAILURES_BEFORE_LOCK)
            by_address = self._addresses.setdefault(address, _Counter())
            self._bump(by_address, now, FAILURES_BEFORE_ADDRESS_LOCK)

    def record_success(self, email: str, address: str) -> None:
        """Clear the pair's counter. The address counter is left alone: one
        correct password must not wipe out evidence of spraying other accounts.
        """
        with self._lock:
            self._pairs.pop(self._pair_key(email, address), None)

    def reset(self) -> None:
        """Forget every counter (used by tests between runs)."""
        with self._lock:
            self._pairs.clear()
            self._addresses.clear()

    @staticmethod
    def _pair_key(email: str, address: str) -> tuple[str, str]:
        """The counter key for an email from an address; the email is folded to lower case."""
        return (email.strip().lower(), address)

    @staticmethod
    def _bump(counter: _Counter, now: float, threshold: int) -> None:
        """Add one failure and, if that crosses the threshold, set how long the key stays locked."""
        counter.failures += 1
        counter.last_seen = now
        wait = lock_seconds(counter.failures, threshold)
        if wait:
            counter.locked_until = now + wait

    def _prune(self, now: float) -> None:
        """At most once a minute, drop counters that are old and no longer locked."""
        if now - self._last_prune < PRUNE_EVERY_SECONDS:
            return
        self._last_prune = now
        for table in (self._pairs, self._addresses):
            stale = [
                key
                for key, counter in table.items()
                if now - counter.last_seen > FORGET_AFTER_SECONDS and counter.locked_until <= now
            ]
            for key in stale:
                del table[key]
