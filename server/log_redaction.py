"""Keep login tokens out of the server's logs.

Found by a security review: the chat WebSocket takes the login token in its URL
(``/ws/chat?token=...``, since a WebSocket handshake can't always carry an
Authorization header), and uvicorn logs every request line. So anyone reading
the host's console or log could copy a working token. This filter rewrites
``token=<anything>`` to ``token=[hidden]`` in uvicorn's log lines before they
are written.
"""

import logging
import re

#: ``token=`` up to the next ``&``, space, quote or end of text.
_TOKEN_IN_URL = re.compile(r"(token=)[^&\s\"']+")

#: The uvicorn loggers that print request lines (HTTP and WebSocket).
_LOGGERS = ("uvicorn.access", "uvicorn.error")


def redact(text: str) -> str:
    """``text`` with every ``token=...`` value replaced by ``[hidden]``."""
    return _TOKEN_IN_URL.sub(r"\1[hidden]", text)


class RedactTokens(logging.Filter):
    """A logging filter that hides tokens in a record's message and arguments."""

    def filter(self, record: logging.LogRecord) -> bool:
        """Rewrite the record in place; never drops it."""
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, tuple):
            record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
        elif isinstance(record.args, dict):
            record.args = {
                k: redact(v) if isinstance(v, str) else v for k, v in record.args.items()
            }
        return True


def install() -> None:
    """Attach the filter to uvicorn's loggers (safe to call more than once)."""
    for name in _LOGGERS:
        logger = logging.getLogger(name)
        if not any(isinstance(f, RedactTokens) for f in logger.filters):
            logger.addFilter(RedactTokens())
