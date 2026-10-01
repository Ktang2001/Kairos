from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from server.api.auth import router as auth_router
from server.api.dashboard import router as dashboard_router
from server.api.health import router as health_router
from server.api.messages import router as messages_router
from server.api.projects import router as projects_router
from server.api.protection import (
    BodySizeLimitMiddleware,
    LocalOnlyDocsMiddleware,
    number_too_large,
)
from server.api.tasks import router as tasks_router
from server.api.teams import router as teams_router
from server.db.session import get_db
from server.services import auth_service
from server.services.login_throttle import LoginThrottle


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Make sure the role rows exist before the first request is served.

    A database built by ``alembic upgrade head`` has a ``roles`` table but no
    rows in it, and without them every registration fails with a 500.

    The session comes from ``get_db`` -- honouring any dependency override --
    so the test suite's throwaway database is the one that gets seeded, not
    the development file.
    """
    get_session = app.dependency_overrides.get(get_db, get_db)
    session_gen = get_session()
    db = next(session_gen)
    try:
        auth_service.ensure_roles(db)
    except OperationalError as exc:
        raise RuntimeError(
            "The database has not been set up. From the repo root, run:\n"
            "    alembic -c server/db/alembic.ini upgrade head"
        ) from exc
    finally:
        session_gen.close()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="Kairos API", lifespan=lifespan)

    # One throttle per app instance, so each test app starts with clean counters.
    app.state.login_throttle = LoginThrottle()
    # Middleware added last runs first: docs check, then the body-size limit.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(LocalOnlyDocsMiddleware)
    app.add_exception_handler(OverflowError, number_too_large)

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(messages_router)
    app.include_router(teams_router)
    app.include_router(projects_router)
    app.include_router(tasks_router)
    app.include_router(dashboard_router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    # proxy_headers=False: no proxy sits in front of Kairos, so X-Forwarded-For
    # must not be trusted (it would let a caller dodge the login lockout).
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True, proxy_headers=False)
