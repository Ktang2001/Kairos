"""GET /dashboard: project statistics for the signed-in user (goal #7)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import get_current_user
from server.db.session import get_db
from server.models.user import User
from server.schemas.dashboard import DashboardOut
from server.services import dashboard_service
from server.services.auth_service import utcnow

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> DashboardOut:
    """Totals, the caller's own work, per-project progress and team workload,
    across every team the caller can see (admins: all teams).

    "Today" is the hosting computer's local date; it is echoed back in the
    response as ``today`` so the client can show what the figures are against.
    """
    return dashboard_service.build_dashboard(
        db, current_user, today=dashboard_service.local_today(), now=utcnow()
    )
