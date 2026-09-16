from sqlalchemy.orm import Mapped, mapped_column

from server.models.base import Base


class Role(Base):
    """Defines what a user can view/edit (e.g. admin, project lead, member)."""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
