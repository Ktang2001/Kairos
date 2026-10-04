from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class ServerSettings(Base):
    """Singleton row (id=1) holding this host's self-reported identity and file-storage config."""

    __tablename__ = "server_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    display_name: Mapped[str]
    upload_root: Mapped[str]
    max_upload_size_bytes: Mapped[int]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now(), nullable=False
    )
