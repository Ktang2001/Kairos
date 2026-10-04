import uuid
from collections.abc import Iterator
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from server import crypto
from server.models.attachment import Attachment
from server.models.chat_message import ChatMessage
from server.models.server_settings import ServerSettings

CHUNK_SIZE = 1024 * 1024  # 1 MiB
_SAFE_SUFFIX_MAX_LEN = 16


class UploadTooLargeError(Exception):
    """Raised when a file exceeds the server's configured max_upload_size_bytes."""


def _get_settings(db: Session) -> ServerSettings:
    settings = db.get(ServerSettings, 1)
    if settings is None:
        raise RuntimeError("server_settings row is missing - it should be seeded by migration")
    return settings


def _safe_suffix(original_filename: str) -> str:
    """Extract a short, conservative extension from a client-supplied filename.

    Never used on its own to build a path - only appended to a server-generated
    uuid. Anything that doesn't look like a plain extension (too long, non
    alphanumeric) is dropped entirely rather than sanitized, since there is no
    legitimate use case this project needs that requires guessing at intent here.
    """
    suffix = Path(original_filename).suffix
    if not suffix or len(suffix) > _SAFE_SUFFIX_MAX_LEN:
        return ""
    if not suffix[1:].isalnum():
        return ""
    return suffix.lower()


def _resolve_upload_root(upload_root: str) -> Path:
    root = Path(upload_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _contained_path(root: Path, filename: str) -> Path:
    """Resolve `filename` under `root` and assert the result is actually inside it.

    Defense-in-depth: `filename` here is always server-generated (a uuid4 hex),
    never client-derived, but this makes the containment guarantee concrete and
    independently testable rather than relying solely on that invariant.
    """
    target = (root / filename).resolve()
    if not target.is_relative_to(root):
        raise ValueError("resolved attachment path escapes the upload root")
    return target


def save_attachment(
    db: Session,
    conversation_id: int,
    uploaded_by_user_id: int,
    upload: UploadFile,
    caption: str | None = None,
    client_token: str | None = None,
) -> ChatMessage:
    """Stream `upload` to disk under the configured upload root, enforcing the max
    size limit, then persist a ChatMessage + Attachment row in one transaction.

    Idempotent on `client_token`, same as chat_service.create_message, so an
    offline-outbox retry never stores the same file twice.
    """
    if client_token:
        existing = db.scalars(
            select(ChatMessage).where(ChatMessage.client_token == client_token)
        ).first()
        if existing is not None:
            upload.file.close()
            return existing

    settings = _get_settings(db)
    root = _resolve_upload_root(settings.upload_root)

    stored_filename = f"{uuid.uuid4().hex}{_safe_suffix(upload.filename or '')}"
    target_path = _contained_path(root, stored_filename)

    key = crypto.get_default_key()
    # A fresh random nonce base per file - required so two different files never
    # reuse the same (key, nonce) pair under AES-GCM (see server/crypto.py).
    file_nonce = crypto.generate_file_nonce()
    size_bytes = 0
    try:
        with target_path.open("wb") as out_file:
            out_file.write(file_nonce)
            chunk_index = 0
            while chunk := upload.file.read(CHUNK_SIZE):
                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_size_bytes:
                    raise UploadTooLargeError(
                        f"upload exceeds the {settings.max_upload_size_bytes}-byte limit"
                    )
                # Encrypted at rest (see server/crypto.py) - chunked AESGCM rather
                # than Fernet, since a complete-blob cipher would mean buffering an
                # entire video file in memory to encrypt it.
                out_file.write(crypto.encrypt_chunk(key, file_nonce, chunk_index, chunk))
                chunk_index += 1
    except Exception:
        target_path.unlink(missing_ok=True)
        raise
    finally:
        upload.file.close()

    message = ChatMessage(
        conversation_id=conversation_id,
        sender_user_id=uploaded_by_user_id,
        body=caption,
        client_token=client_token,
    )
    db.add(message)
    db.flush()

    db.add(
        Attachment(
            chat_message_id=message.id,
            original_filename=upload.filename or "file",
            stored_filename=stored_filename,
            content_type=upload.content_type,
            size_bytes=size_bytes,
            uploaded_by_user_id=uploaded_by_user_id,
        )
    )
    db.commit()
    db.refresh(message)
    return message


def resolve_download_path(db: Session, attachment: Attachment) -> Path:
    settings = _get_settings(db)
    root = _resolve_upload_root(settings.upload_root)
    return _contained_path(root, attachment.stored_filename)


def stream_decrypted_attachment(path: Path) -> Iterator[bytes]:
    """Decrypts the file at `path` (written chunk-by-chunk by save_attachment)
    and yields it back in order, so the API layer can stream a response without
    ever buffering the whole file in memory."""
    key = crypto.get_default_key()
    with path.open("rb") as in_file:
        file_nonce = in_file.read(crypto.NONCE_SIZE)
        yield from crypto.decrypt_stream(key, file_nonce, in_file.read)
