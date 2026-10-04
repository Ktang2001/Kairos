from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from server.models.user import User


def get_user(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def search_users(db: Session, query: str, limit: int = 20) -> list[User]:
    """Find users by a case-insensitive partial match on name or email.

    Returns an empty list for a blank query rather than dumping every user.
    """
    query = query.strip()
    if not query:
        return []

    like = f"%{query}%"
    stmt = (
        select(User)
        .where(or_(User.name.ilike(like), User.email.ilike(like)))
        .order_by(User.name)
        .limit(limit)
    )
    return list(db.scalars(stmt))
