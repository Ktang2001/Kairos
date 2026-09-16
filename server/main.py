from fastapi import FastAPI

from server.api.health import router as health_router


def create_app() -> FastAPI:
    app = FastAPI(title="Kairos API")
    app.include_router(health_router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
