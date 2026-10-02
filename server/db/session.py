"""The database engine and the per-request session.

Concurrency (found by stress testing): several rules are "check, then
write" -- "is X still a member?" before making X the lead, "is there
another admin?" before a demotion. SQLite by default only locks the
database at the *write*, so two requests could both pass their checks and
then both write, breaking the rule (a team whose lead isn't a member; no
admins left). Three settings fix that:

* ``BEGIN IMMEDIATE`` for requests that change data: the write lock is
  taken *before* the request's first read, so its checks and its write
  happen as one step and simultaneous changes queue up one at a time.
  Reads (GET) use an ordinary transaction and never queue.
* WAL journal mode: reads never wait for a write in progress.
* A 30 s busy timeout: a queued write waits instead of failing with
  "database is locked" after SQLite's default 5 s.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from server.db.config import DATABASE_URL

#: Seconds a request waits for the write lock before giving up.
BUSY_TIMEOUT_SECONDS = 30

#: HTTP methods that only read, and so never need the write lock.
READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

#: Writes that must not hold the lock from the start: both spend ~0.1 s
#: hashing a password, which would make every other write wait behind them.
#: They call ``begin_write`` themselves once the slow part is done.
NO_LOCK_PATHS = frozenset({"/auth/login", "/auth/register"})

_BEGIN_MODE = "sqlite_begin_mode"


def configure_sqlite(engine: Engine) -> Engine:
    """Apply the settings above to ``engine``. Also used by the tests, so
    they run against the same behaviour as the real server.
    """

    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _record) -> None:
        # Hand transaction control to SQLAlchemy (the "begin" hook below):
        # the sqlite3 driver's own automatic BEGIN can't be IMMEDIATE.
        dbapi_connection.isolation_level = None
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_SECONDS * 1000}")
        cursor.close()

    @event.listens_for(engine, "begin")
    def _on_begin(connection) -> None:
        mode = connection.get_execution_options().get(_BEGIN_MODE, "DEFERRED")
        connection.exec_driver_sql(f"BEGIN {mode}")

    return engine


def needs_write_lock(request: Request | None) -> bool:
    return (
        request is not None
        and request.method not in READ_ONLY_METHODS
        and request.url.path not in NO_LOCK_PATHS
    )


def open_session(factory: sessionmaker[Session], request: Request | None) -> Iterator[Session]:
    """Yield a session for one request, holding the write lock from the
    start if the request changes data.
    """
    db = factory()
    try:
        if needs_write_lock(request):
            # Opening the connection now, with this option, makes its first
            # transaction BEGIN IMMEDIATE -- before any check reads a row.
            db.connection(execution_options={_BEGIN_MODE: "IMMEDIATE"})
        yield db
    finally:
        db.close()


def begin_write(db: Session) -> None:
    """Finish the current transaction and start one holding the write lock.

    For requests that do slow work (password hashing) before they write.
    Needed in WAL mode: a transaction that has *read* cannot later write if
    someone else wrote in between -- SQLite refuses at once ("database is
    locked"), however long the busy timeout. Starting a fresh write
    transaction after the slow part avoids that without holding the lock
    during the hashing.
    """
    db.commit()
    db.connection(execution_options={_BEGIN_MODE: "IMMEDIATE"})


engine = configure_sqlite(
    create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False, "timeout": BUSY_TIMEOUT_SECONDS},
    )
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db(request: Request = None) -> Iterator[Session]:  # type: ignore[assignment]
    """FastAPI dependency that yields a request-scoped DB session.

    ``request`` defaults to None for callers outside a request (start-up),
    which get an ordinary transaction.
    """
    yield from open_session(SessionLocal, request)
