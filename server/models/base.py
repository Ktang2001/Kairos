"""The base class every database model inherits from (see server/models/)."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base for all Kairos ORM models."""
