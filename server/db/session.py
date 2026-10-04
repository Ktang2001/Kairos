from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DB_PATH = Path(__file__).parent / "kairos.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency that yields a request-scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_session_factory() -> sessionmaker[Session]:
    """A dependency that resolves to the active sessionmaker itself.

    For code that needs to open and close its own short-lived session rather than
    hold a request-scoped one for its whole lifetime - namely the WebSocket endpoint
    (server/api/ws_chat.py), where `Depends(get_db)` would otherwise stay open for
    the entire connection. Overridable in tests the same way as `get_db`.
    """
    return SessionLocal
