from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.api.dependencies import get_current_user_id
from server.db.session import get_db
from server.schemas.people import UserProfile, UserSummary
from server.services import people_service

router = APIRouter(prefix="/people", tags=["people"])


@router.get("/search", response_model=list[UserSummary])
def search_people(
    q: str = "", limit: int = 20, db: Session = Depends(get_db)  # noqa: B008
) -> list[UserSummary]:
    """Public, read-only directory search - needed to bootstrap the placeholder identity
    picker before any user is "logged in", so it is intentionally not gated by
    `get_current_user_id`. Revisit once real auth exists.
    """
    users = people_service.search_users(db, query=q, limit=limit)
    return [UserSummary.model_validate(u) for u in users]


@router.get("/me", response_model=UserProfile)
def get_my_profile(
    current_user_id: int = Depends(get_current_user_id),
    db: Session = Depends(get_db),  # noqa: B008
) -> UserProfile:
    """The caller's own profile, role included - this is how the client learns
    whether to show admin-only UI (e.g. remote server settings). Must be registered
    before GET /{user_id} so "me" isn't swallowed by that path param.
    """
    user = people_service.get_user(db, current_user_id)
    return UserProfile(id=user.id, name=user.name, email=user.email, role=user.role.name)


@router.get("/{user_id}", response_model=UserSummary)
def get_person(user_id: int, db: Session = Depends(get_db)) -> UserSummary:  # noqa: B008
    """Resolve a single user id to a display name - e.g. for labeling a direct
    conversation by the other participant's name. Public, same reasoning as /search.
    """
    user = people_service.get_user(db, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return UserSummary.model_validate(user)
