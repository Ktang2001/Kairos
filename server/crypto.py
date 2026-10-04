"""At-rest encryption for chat message text and attachment files.

One symmetric key protects both: chat message bodies (via a Fernet-wrapped
SQLAlchemy TypeDecorator - see server/models/chat_message.py) and attachment file
contents (via chunked AESGCM, since attachments need streaming - see
server/services/attachment_service.py; Fernet operates on one complete blob,
which would mean buffering an entire video file in memory).

Scope, stated plainly: this protects server/db/kairos.db and the upload folder's
contents if they're copied out on their own (a backup, a stolen drive). It does
NOT protect against a full host compromise, since the running server needs this
key readable to do its job - the key sits right next to what it encrypts.

`get_default_key()` is the lazy, monkeypatchable seam tests use to point at an
isolated per-test key file instead of the real one (see tests/server/conftest.py) -
DEFAULT_KEY_PATH is read at call time, not cached, the same way
attachment_service.py reads `upload_root` fresh on every call rather than once.
"""

import base64
import os
import struct
from collections.abc import Callable, Iterator
from pathlib import Path

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_SIZE = 32
NONCE_SIZE = 12  # AESGCM's standard nonce size
LENGTH_PREFIX_SIZE = 4  # struct ">I" - max ~4GiB per encrypted chunk, way above CHUNK_SIZE
DEFAULT_KEY_PATH = Path(__file__).resolve().parent / "db" / "kairos.key"


def get_or_create_key(path: Path) -> bytes:
    """Return the key at `path`, generating a new random one on first use."""
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(KEY_SIZE)
    path.write_bytes(key)
    path.chmod(0o600)
    return key


def get_default_key() -> bytes:
    return get_or_create_key(DEFAULT_KEY_PATH)


def _fernet(key: bytes) -> Fernet:
    # Fernet wants a base64-urlsafe-encoded key; we store/generate the raw bytes
    # so the same key also works directly as an AESGCM key below.
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_text(key: bytes, plaintext: str) -> bytes:
    return _fernet(key).encrypt(plaintext.encode("utf-8"))


def decrypt_text(key: bytes, token: bytes) -> str:
    return _fernet(key).decrypt(token).decode("utf-8")


def generate_file_nonce() -> bytes:
    """One random per-file nonce base - the thing that actually makes nonces
    unique across different files. AES-GCM's rule is no (key, nonce) pair may
    ever repeat under one key, across ALL encryptions - not just within one
    file - so a per-file nonce base is written once at the start of each
    encrypted file (see attachment_service.save_attachment) rather than letting
    every file restart its chunk nonces at the same values under the same key."""
    return os.urandom(NONCE_SIZE)


def _chunk_nonce(file_nonce: bytes, chunk_index: int) -> bytes:
    """Combines the per-file random base with the chunk index (mod 2**96) so
    chunks within one file never repeat a nonce either, same as before."""
    base = int.from_bytes(file_nonce, "big")
    combined = (base + chunk_index) % (1 << (NONCE_SIZE * 8))
    return combined.to_bytes(NONCE_SIZE, "big")


def encrypt_chunk(key: bytes, file_nonce: bytes, chunk_index: int, chunk: bytes) -> bytes:
    """One AEAD-encrypted, length-framed record: [4-byte length][ciphertext+tag].
    The length prefix is what lets decrypt_stream read chunks back one at a time
    without a separate index."""
    ciphertext = AESGCM(key).encrypt(_chunk_nonce(file_nonce, chunk_index), chunk, None)
    return struct.pack(">I", len(ciphertext)) + ciphertext


def decrypt_stream(key: bytes, file_nonce: bytes, read: Callable[[int], bytes]) -> Iterator[bytes]:
    """Reads framed chunks via `read(n)` (e.g. an open file's `.read`) and yields
    each one decrypted, in order, until EOF. `file_nonce` must be the same value
    passed to encrypt_chunk when this file was written."""
    aesgcm = AESGCM(key)
    chunk_index = 0
    while length_prefix := read(LENGTH_PREFIX_SIZE):
        (length,) = struct.unpack(">I", length_prefix)
        ciphertext = read(length)
        yield aesgcm.decrypt(_chunk_nonce(file_nonce, chunk_index), ciphertext, None)
        chunk_index += 1
