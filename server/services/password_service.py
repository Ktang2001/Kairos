"""Password hashing and verification using only the standard library.

``hashlib.scrypt`` is a memory-hard key-derivation function built into Python,
so the project gets a respectable password-hashing primitive without adding a
dependency (see Rules.md: no new major dependency without flagging it first).

The stored format is self-describing -- ``scrypt$n$r$p$<salt>$<hash>`` -- so the
cost parameters can be raised later without invalidating existing passwords:
verification always uses the parameters recorded next to the hash, not the
current module constants.

MERGE-CRITICAL (whole file): the only place passwords are hashed and
checked. Every stored ``users.password_hash`` is in this format; a second
hashing scheme elsewhere (e.g. PBKDF2 in auth_service) would make those
accounts unable to sign in. Guarded by: tests/server/test_password_service.py.
"""

import base64
import hashlib
import hmac
import secrets
from functools import lru_cache

ALGORITHM = "scrypt"

#: Cost parameters. ``n`` is the CPU/memory cost and must be a power of two,
#: ``r`` is the block size and ``p`` the parallelisation factor. n=2**15 with
#: r=8 needs 128*n*r = 32 MiB of memory per hash, which is far more than a
#: cheap per-guess attack wants to pay, while staying well under a second on
#: the machines this app runs on.
SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1

#: ``hashlib.scrypt`` inherits OpenSSL's 32 MiB memory cap, which n=2**15 at
#: r=8 sits exactly on -- it fails with "memory limit exceeded" rather than
#: hashing. Raise the cap explicitly. The real requirement is
#: 128*r*(n+p+2) ~= 32 MiB, so 64 MiB leaves safe headroom.
SCRYPT_MAXMEM = 64 * 1024 * 1024

#: Length of the derived key, in bytes.
KEY_LENGTH = 32

#: Length of the random per-password salt, in bytes. 128 bits means a
#: precomputed table would have to be rebuilt for every single password.
SALT_LENGTH = 16

#: Upper bounds accepted when *parsing* a stored hash. A corrupted or
#: tampered row must not be able to ask for gigabytes of memory, so anything
#: outside these limits is treated as "not a valid hash" instead of running.
MAX_PARSED_N = SCRYPT_N * 4
MAX_PARSED_R = 32
MAX_PARSED_P = 16


def _encode(raw: bytes) -> str:
    """Bytes to base64 text, for storing in the hash string."""
    return base64.b64encode(raw).decode("ascii")


def _decode(text: str) -> bytes:
    """Base64 text back to bytes; raises on anything malformed."""
    return base64.b64decode(text.encode("ascii"), validate=True)


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    """Run scrypt with these settings and return the derived key."""
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        maxmem=SCRYPT_MAXMEM,
        dklen=KEY_LENGTH,
    )


def hash_password(password: str) -> str:
    """Return a new self-describing hash string for ``password``."""
    salt = secrets.token_bytes(SALT_LENGTH)
    derived = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return f"{ALGORITHM}${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_encode(salt)}${_encode(derived)}"


def _parse(stored: str) -> tuple[bytes, bytes, int, int, int] | None:
    """Split a stored hash into (salt, expected, n, r, p), or None if invalid."""
    parts = stored.split("$")
    if len(parts) != 6:
        return None

    algorithm, n_raw, r_raw, p_raw, salt_raw, hash_raw = parts
    if algorithm != ALGORITHM:
        return None

    try:
        n, r, p = int(n_raw), int(r_raw), int(p_raw)
        salt = _decode(salt_raw)
        expected = _decode(hash_raw)
    except (ValueError, TypeError):
        return None

    # Guard the parameters *before* deriving: scrypt allocates memory based on
    # n and r, so an unchecked value from a corrupt row is a denial-of-service.
    if n < 2 or n > MAX_PARSED_N or (n & (n - 1)) != 0:
        return None
    if not 1 <= r <= MAX_PARSED_R or not 1 <= p <= MAX_PARSED_P:
        return None
    if len(expected) != KEY_LENGTH or len(salt) < SALT_LENGTH:
        return None

    return salt, expected, n, r, p


def verify_password(password: str, stored: str) -> bool:
    """Return True if ``password`` matches the stored hash string.

    Returns False rather than raising for anything unparseable, so a corrupt
    row produces a failed login instead of a 500.
    """
    parsed = _parse(stored)
    if parsed is None:
        return False

    salt, expected, n, r, p = parsed
    derived = _derive(password, salt, n, r, p)
    return hmac.compare_digest(derived, expected)


@lru_cache(maxsize=1)
def dummy_hash() -> str:
    """A valid hash of a value nobody can supply, for timing equalisation.

    Login must take roughly the same time whether or not the email exists.
    Returning immediately for an unknown email lets an attacker discover which
    addresses are registered just by timing the responses; verifying against
    this hash instead burns the same scrypt work. Computed once, on first use,
    so importing this module stays cheap.
    """
    return hash_password(secrets.token_urlsafe(32))
