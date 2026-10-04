from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.db.session import get_db
from server.schemas.auth import LoginRequest, SignupRequest
from server.schemas.people import UserSummary
from server.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/signup", response_model=UserSummary)
def signup(payload: SignupRequest, db: Session = Depends(get_db)) -> UserSummary:  # noqa: B008
    """Creates a real account (hashed password, verified on login) - but per-request
    authorization elsewhere still relies on the placeholder X-Kairos-User-Id header
    (see server/api/dependencies.py) until real sessions/tokens replace it.
    """
    try:
        user = auth_service.create_user(
            db, name=payload.name, email=payload.email, password=payload.password
        )
    except ValueError as exc:
        status_code = 409 if "already registered" in str(exc) else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return UserSummary.model_validate(user)


@router.post("/login", response_model=UserSummary)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> UserSummary:  # noqa: B008
    user = auth_service.authenticate(db, email=payload.email, password=payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Incorrect email or password")
    return UserSummary.model_validate(user)
