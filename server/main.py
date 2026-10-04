from fastapi import FastAPI

from server.api.attachments import router as attachments_router
from server.api.auth import router as auth_router
from server.api.chat_messages import router as chat_messages_router
from server.api.conversations import router as conversations_router
from server.api.health import router as health_router
from server.api.messages import router as messages_router
from server.api.people import router as people_router
from server.api.server_settings import router as server_settings_router
from server.api.ws_chat import router as ws_chat_router


def create_app() -> FastAPI:
    app = FastAPI(title="Kairos API")
    app.include_router(health_router)
    app.include_router(messages_router)
    app.include_router(auth_router)
    app.include_router(people_router)
    app.include_router(conversations_router)
    app.include_router(chat_messages_router)
    app.include_router(attachments_router)
    app.include_router(server_settings_router)
    app.include_router(ws_chat_router)
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server.main:app", host="0.0.0.0", port=8000, reload=True)
