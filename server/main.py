"""The Kairos server: builds the FastAPI app that every request goes through.

``create_app()`` assembles it from three kinds of parts:

* **start-up** (``lifespan``): makes sure the role rows exist;
* **protections** (middleware + error handlers from ``server/api/protection.py``)
  that run before any route: request-size limit, local-only API docs, a
  clean 422 for absurdly large numbers;
* **routers**, one per area: health, auth (sign-in/accounts), messages,
  teams, users (admin).

Run it with ``python -m server.main`` or through the server window
(``python -m server.gui``).

MERGE NOTE: when another branch brings new routers, *add* their
``include_router`` lines to ``create_app`` below. Do not take another branch's
older copy of this file: it would silently drop the protections, the login
lockout and the role set-up (search this file for MERGE-CRITICAL).
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.exc import OperationalError

from server.api.auth import router as auth_router
from server.api.health import router as health_router
from server.api.messages import router as messages_router
from server.api.protection import (
    BodySizeLimitMiddleware,
    LocalOnlyDocsMiddleware,
    number_too_large,
)
from server.api.teams import router as teams_router
from server.api.users import router as users_router
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
    # MERGE-CRITICAL: keep this start-up step. If lost: on a freshly migrated
    # database every registration fails with a 500 (no roles to assign).
    # Guarded by: tests/server/test_startup.py.
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
    """Build the FastAPI app: protections, login lockout and every router. Tests call this for a
    fresh app with clean state.
    """
    app = FastAPI(title="Kairos API", lifespan=lifespan)

    # MERGE-CRITICAL: keep these four lines. If lost: no login lockout
    # (passwords can be guessed endlessly), one huge request can exhaust the
    # host's memory, the API map is shown to anyone on the network, and
    # oversized ids crash requests with a 500.
    # Guarded by: tests/server/test_security.py.
    #
    # One throttle per app instance, so each test app starts with clean counters.
    app.state.login_throttle = LoginThrottle()
    # Middleware added last runs first: docs check, then the body-size limit.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(LocalOnlyDocsMiddleware)
    app.add_exception_handler(OverflowError, number_too_large)

    # One router per area of the API. New areas: add a line, keep the others.

    app.include_router(health_router)
    app.include_router(auth_router)
    app.include_router(messages_router)
    app.include_router(teams_router)
    app.include_router(users_router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    # MERGE-CRITICAL: keep proxy_headers=False (here and in server/gui.py).
    # No proxy sits in front of Kairos, so X-Forwarded-For must not be
    # trusted: it would let a caller pick their own address and dodge the
    # login lockout. Guarded by: tests/server/test_gui.py.
    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True, proxy_headers=False)
