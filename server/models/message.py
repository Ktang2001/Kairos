"""The ``messages`` table: short test messages sent from the client's Messages tab and shown in the
server window.
"""

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class Message(Base):
    """A single client->server ping used to smoke-test connectivity."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    sender: Mapped[str]
    content: Mapped[str]
    # TODO(attachments): add nullable columns for an attached file, e.g.
    # attachment_kind ("file" / "image" / "audio"), attachment_name (original
    # file name, for display), attachment_path (where the server stored it) and
    # attachment_size. Then generate a migration:
    #   alembic -c server/db/alembic.ini revision --autogenerate -m "message attachments"
    created_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), nullable=False
    )
