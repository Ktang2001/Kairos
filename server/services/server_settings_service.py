from pathlib import Path

from sqlalchemy.orm import Session

from server.models.server_settings import ServerSettings


def get_settings(db: Session) -> ServerSettings:
    settings = db.get(ServerSettings, 1)
    if settings is None:
        raise RuntimeError("server_settings row is missing - it should be seeded by migration")
    return settings


def update_settings(
    db: Session,
    display_name: str | None = None,
    upload_root: str | None = None,
    max_upload_size_bytes: int | None = None,
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
            raise ValueError(f"upload_root is not writable: {exc}") from exc
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

    db.commit()
    db.refresh(settings)
    return settings
