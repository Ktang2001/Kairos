"""Tests for the scrypt password hashing service.

These cover the failure modes that matter: a hash that will not verify, a
corrupt or hostile stored value that must be rejected rather than crashing the
login route, and the salting that stops two identical passwords producing
identical rows.
"""

import pytest

from server.services import password_service


def test_a_correct_password_verifies() -> None:
    stored = password_service.hash_password("correct-horse-battery")

    assert password_service.verify_password("correct-horse-battery", stored)


def test_a_wrong_password_does_not_verify() -> None:
    stored = password_service.hash_password("correct-horse-battery")

    assert not password_service.verify_password("correct-horse-batter", stored)
    assert not password_service.verify_password("", stored)
    assert not password_service.verify_password("CORRECT-HORSE-BATTERY", stored)


def test_the_same_password_hashes_differently_each_time() -> None:
    """A per-password salt is what stops two users with the same password from
    being visible as a shared row, and stops one precomputed table serving all
    of them."""
    first = password_service.hash_password("same-password")
    second = password_service.hash_password("same-password")

    assert first != second
    assert password_service.verify_password("same-password", first)
    assert password_service.verify_password("same-password", second)


def test_the_hash_is_self_describing_and_hides_the_password() -> None:
    stored = password_service.hash_password("hunter2")

    algorithm, n, r, p, salt, digest = stored.split("$")
    assert algorithm == password_service.ALGORITHM
    # The parameters are recorded alongside the hash so they can be raised later
    # without invalidating passwords hashed under the old ones.
    assert int(n) == password_service.SCRYPT_N
    assert int(r) == password_service.SCRYPT_R
    assert int(p) == password_service.SCRYPT_P
    assert len(salt) > 0
    assert len(digest) > 0
    assert "hunter2" not in stored


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "not-a-hash",
        "scrypt",
        "scrypt$32768$8$1$salt$digest",
        "bcrypt$32768$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
        "scrypt$notanumber$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    ],
)
def test_unparseable_stored_values_are_rejected_not_raised(stored: str) -> None:
    """A corrupt row must produce a failed login, never a 500."""
    assert password_service.verify_password("anything", stored) is False


def test_an_absurd_cost_parameter_is_rejected_without_deriving() -> None:
    """A tampered n must not be honoured: scrypt allocates memory from n and r,
    so accepting this would be a denial-of-service in one request."""
    hostile = "scrypt$1073741824$8$1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 43 + "="

    assert password_service.verify_password("anything", hostile) is False


def test_a_non_power_of_two_cost_parameter_is_rejected() -> None:
    """scrypt requires n to be a power of two; anything else is not our hash."""
    hostile = "scrypt$1000$8$1$AAAAAAAAAAAAAAAAAAAAAA==$" + "A" * 43 + "="

    assert password_service.verify_password("anything", hostile) is False


def test_a_truncated_digest_is_rejected() -> None:
    """A digest that is not KEY_LENGTH bytes cannot be a hash we produced."""
    truncated = f"scrypt${password_service.SCRYPT_N}$8$1$AAAAAAAAAAAAAAAAAAAAAA==$AAAA"

    assert password_service.verify_password("anything", truncated) is False


def test_a_short_salt_is_rejected() -> None:
    short_salt = f"scrypt${password_service.SCRYPT_N}$8$1$AAAA$" + "A" * 43 + "="

    assert password_service.verify_password("anything", short_salt) is False


def test_unicode_passwords_round_trip() -> None:
    """Encoding is explicit utf-8, so non-ascii passwords must not break."""
    password = "correct horse battery staple -\u00e9\u00e8\u00fc\u4e2d\u6587"
    stored = password_service.hash_password(password)

    assert password_service.verify_password(password, stored)


def test_a_password_of_the_maximum_accepted_length_round_trips() -> None:
    password = "a" * 128
    stored = password_service.hash_password(password)

    assert password_service.verify_password(password, stored)


def test_the_dummy_hash_is_a_real_hash_that_nothing_verifies() -> None:
    """Login burns this hash for unknown emails, so it must be a genuine,
    expensive hash -- and one no supplied password should ever match."""
    dummy = password_service.dummy_hash()

    assert dummy.startswith(f"{password_service.ALGORITHM}$")
    assert not password_service.verify_password("", dummy)
    assert not password_service.verify_password("password", dummy)


def test_the_dummy_hash_is_computed_once_and_reused() -> None:
    """It is only for timing equalisation; recomputing it per request would
    double the cost of every failed login."""
    assert password_service.dummy_hash() is password_service.dummy_hash()
