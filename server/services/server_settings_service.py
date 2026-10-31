import logging
from pathlib import Path
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from server.models.server_settings import ServerSettings

logger = logging.getLogger(__name__)


def get_settings(db: Session) -> ServerSettings:
    settings = db.get(ServerSettings, 1)
    if settings is None:
        raise RuntimeError("server_settings row is missing - it should be seeded by migration")
    return settings


#: Shown when a Jitsi address is refused.
JITSI_URL_MESSAGE = "The meeting server must be an https:// address, like https://meet.jit.si"


def normalize_jitsi_base_url(url: str) -> str:
    """Check a Jitsi server address and return it without a trailing slash.

    Only a plain https:// address is accepted: meeting links are opened in
    people's browsers, so an http:// one would send the call unencrypted, and
    a query, fragment or user:password part has no business in a base address
    that room names are appended to. A path is allowed (a self-hosted Jitsi
    under /meet). Raises ValueError otherwise.
    """
    url = url.strip().rstrip("/")
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.query
        or parts.fragment
        or parts.username
        or parts.password
        or any(char.isspace() for char in url)
    ):
        raise ValueError(JITSI_URL_MESSAGE)
    return url


def update_settings(
    db: Session,
    display_name: str | None = None,
    upload_root: str | None = None,
    max_upload_size_bytes: int | None = None,
    jitsi_base_url: str | None = None,
) -> ServerSettings:
    """Update any subset of the server's settings.

    Validates `upload_root` is an actually-writable directory before persisting it.
    The host's own Server GUI (in-process) and a remote global-admin's PUT /server/info
    both funnel through this one function, so there is exactly one place that
    normalizes/validates these values (see server/gui.py and server/api/server_settings.py).
    """
    settings = get_settings(db)

    if upload_root is not None:
        resolved = Path(upload_root).expanduser().resolve()
        try:
            resolved.mkdir(parents=True, exist_ok=True)
            probe = resolved / ".kairos_write_check"
            probe.touch()
            probe.unlink()
        except OSError as exc:
            # The OS error quotes paths on the host; this message can reach a
            # remote admin's client, so the details go to the server log only.
            logger.error("Upload folder %s is not usable: %s", resolved, exc)
            raise ValueError(
                "That upload folder can't be used: it doesn't exist and can't be created, "
                "or the server isn't allowed to write to it."
            ) from exc
        settings.upload_root = str(resolved)

    if display_name is not None:
        display_name = display_name.strip()
        if not display_name:
            raise ValueError("display_name cannot be empty")
        settings.display_name = display_name

    if max_upload_size_bytes is not None:
        if max_upload_size_bytes <= 0:
            raise ValueError("max_upload_size_bytes must be positive")
        settings.max_upload_size_bytes = max_upload_size_bytes

    if jitsi_base_url is not None:
        settings.jitsi_base_url = normalize_jitsi_base_url(jitsi_base_url)

    db.commit()
    db.refresh(settings)
    return settings
