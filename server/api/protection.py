"""Protections that apply to every request, before any route runs.

* ``BodySizeLimitMiddleware``: refuses request bodies over ``MAX_BODY_BYTES``
  with 413. Without it a single multi-gigabyte request is read into memory in
  full before validation ever looks at it.
* ``LocalOnlyDocsMiddleware``: the interactive API docs (/docs, /redoc,
  /openapi.json) answer only to the computer running the server. Teammates on
  the network get 404, so the API map is not handed to anyone on the Wi-Fi,
  while the host can still use /docs for testing.
* ``number_too_large``: an exception handler for ids beyond what SQLite can
  store (2**63 - 1), which otherwise crash that request with a 500.
"""

from ipaddress import ip_address

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

#: Far above any legitimate request (the largest is a 2000-character message
#: description), far below anything that strains memory.
MAX_BODY_BYTES = 1024 * 1024

DOCS_PATHS = frozenset({"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"})


class _BodyTooLarge(HTTPException):
    """An HTTPException on purpose: FastAPI wraps any *other* error raised
    while reading a body into a generic 400, but re-raises HTTPExceptions, so
    a streamed (chunked) oversized body still gets a proper 413.
    """

    def __init__(self) -> None:
        super().__init__(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Request too large")


async def _send_json(send: Send, status_code: int, detail: str) -> None:
    body = JSONResponse({"detail": detail}, status_code=status_code).body
    await send(
        {
            "type": "http.response.start",
            "status": status_code,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class BodySizeLimitMiddleware:
    """Pure ASGI (not BaseHTTPMiddleware) so it can stop *reading* the body.

    Two checks, because a client can lie or omit the length: the declared
    Content-Length is checked up front, and the bytes actually received are
    counted as they arrive.
    """

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_big = int(declared) > self.max_bytes
            except ValueError:
                await _send_json(send, status.HTTP_400_BAD_REQUEST, "Invalid Content-Length")
                return
            if too_big:
                await _send_json(send, status.HTTP_413_CONTENT_TOO_LARGE, "Request too large")
                return

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await _send_json(send, status.HTTP_413_CONTENT_TOO_LARGE, "Request too large")


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


class LocalOnlyDocsMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["path"] in DOCS_PATHS:
            client = scope.get("client")
            if not _is_loopback(client[0] if client else None):
                await _send_json(send, status.HTTP_404_NOT_FOUND, "Not Found")
                return
        await self.app(scope, receive, send)


async def number_too_large(_request: Request, _exc: OverflowError) -> JSONResponse:
    return JSONResponse(
        {"detail": "A number in the request is too large"},
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )
