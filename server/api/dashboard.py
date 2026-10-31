"""GET /dashboard: project statistics for the signed-in user (goal #7)."""

from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session as OrmSession

from server.api.deps import get_current_user
from server.api.errors import KNOWN_ERRORS, http_error
from server.db.session import get_db
from server.models.user import User
from server.schemas.dashboard import DashboardOut
from server.services import dashboard_service
from server.services.task_service import utcnow

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    today: date | None = None,
    db: OrmSession = Depends(get_db),  # noqa: B008
    current_user: User = Depends(get_current_user),  # noqa: B008
) -> DashboardOut:
    """Totals, the caller's own work, per-project progress and team workload,
    across every team the caller can see (admins: all teams).

    ``today`` is the caller's own date (``?today=2026-11-02``), which "due
    soon" counts from; without it, the hosting computer's. It is echoed back
    in the response so the client can show what the figures are against.
    "Overdue" doesn't need it: it is each deadline's exact moment passing.
    """
    try:
        day = dashboard_service.viewer_today(today)
    except KNOWN_ERRORS as exc:
        raise http_error(exc) from None
    return dashboard_service.build_dashboard(db, current_user, today=day, now=utcnow())
