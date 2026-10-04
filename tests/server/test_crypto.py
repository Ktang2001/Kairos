import os
from collections.abc import Callable

import pytest
from cryptography.fernet import InvalidToken

from server import crypto


def test_encrypt_text_round_trips_and_is_not_plaintext() -> None:
    key = os.urandom(crypto.KEY_SIZE)

    token = crypto.encrypt_text(key, "hello world")

    assert token != b"hello world"
    assert b"hello" not in token
    assert crypto.decrypt_text(key, token) == "hello world"


def _framed_reader(framed: bytes) -> Callable[[int], bytes]:
    """Simulates a file object's .read(n) against a single in-memory buffer."""
    buf = bytearray(framed)

    def _read(n: int) -> bytes:
        data = bytes(buf[:n])
        del buf[:n]
        return data

    return _read


def test_chunked_stream_round_trips_and_is_not_plaintext() -> None:
    key = os.urandom(crypto.KEY_SIZE)
    file_nonce = crypto.generate_file_nonce()
    chunks = [b"A" * 1000, b"B" * 500, b"C" * 42]

    framed = b"".join(
        crypto.encrypt_chunk(key, file_nonce, index, chunk) for index, chunk in enumerate(chunks)
    )
    assert b"A" * 1000 not in framed

    decrypted = b"".join(crypto.decrypt_stream(key, file_nonce, _framed_reader(framed)))
    assert decrypted == b"".join(chunks)


def test_different_files_never_reuse_a_nonce_under_the_same_key() -> None:
    """Regression test: chunk 0 of two different files must not share a nonce
    under the same key - the earlier chunk-index-only nonce scheme broke this."""
    key = os.urandom(crypto.KEY_SIZE)
    nonce_a = crypto.generate_file_nonce()
    nonce_b = crypto.generate_file_nonce()

    # Even at the same chunk index, two files' actual nonces must differ.
    assert crypto._chunk_nonce(nonce_a, 0) != crypto._chunk_nonce(nonce_b, 0)

    chunk = b"same plaintext in both files"
    ciphertext_a = crypto.encrypt_chunk(key, nonce_a, 0, chunk)
    ciphertext_b = crypto.encrypt_chunk(key, nonce_b, 0, chunk)
    assert ciphertext_a != ciphertext_b


def test_decrypt_fails_with_the_wrong_key() -> None:
    key = os.urandom(crypto.KEY_SIZE)
    wrong_key = os.urandom(crypto.KEY_SIZE)
    token = crypto.encrypt_text(key, "secret")

    with pytest.raises(InvalidToken):
        crypto.decrypt_text(wrong_key, token)


def test_get_or_create_key_is_idempotent(tmp_path) -> None:
    key_path = tmp_path / "test.key"

    first = crypto.get_or_create_key(key_path)
    second = crypto.get_or_create_key(key_path)

    assert first == second
    assert len(first) == crypto.KEY_SIZE
