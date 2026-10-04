"""``GET /health``: answers ``{"status": "ok"}`` while the server is up. Needs no sign-in, so it can
be used to check a server address.
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness check: always answers {"status": "ok"}."""
    return {"status": "ok"}
