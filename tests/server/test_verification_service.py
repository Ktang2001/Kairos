from datetime import UTC, datetime, timedelta

import pytest

from server.models.pending_verification import PendingVerification
from server.services import verification_service


def test_create_pending_verification_hashes_the_code_at_rest(db_session, make_user) -> None:
    user = make_user("Alice", "alice@example.com")

    record, code = verification_service.create_pending_verification(db_session, user.id, user.email)

    assert len(code) == verification_service.CODE_LENGTH
    assert code.isdigit()
    assert record.code_hash != code
    assert record.code_hash not in code


def test_verify_code_succeeds_with_correct_code(db_session, make_user) -> None:
    user = make_user("Alice", "alice@example.com")
    _record, code = verification_service.create_pending_verification(
        db_session, user.id, user.email
    )

    result = verification_service.verify_code(db_session, _record.token, code)

    assert result == user.id


def test_verify_code_fails_with_wrong_code(db_session, make_user) -> None:
    user = make_user("Alice", "alice@example.com")
    record, _code = verification_service.create_pending_verification(
        db_session, user.id, user.email
    )

    assert verification_service.verify_code(db_session, record.token, "000000") is None


def test_verify_code_is_one_time_use(db_session, make_user) -> None:
    user = make_user("Alice", "alice@example.com")
    record, code = verification_service.create_pending_verification(db_session, user.id, user.email)

    assert verification_service.verify_code(db_session, record.token, code) == user.id
    assert verification_service.verify_code(db_session, record.token, code) is None


def test_verify_code_fails_after_expiry(db_session, make_user) -> None:
    user = make_user("Alice", "alice@example.com")
    record, code = verification_service.create_pending_verification(db_session, user.id, user.email)
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db_session.commit()

    assert verification_service.verify_code(db_session, record.token, code) is None


def test_five_wrong_attempts_lock_out_the_pending_attempt(db_session, make_user) -> None:
    user = make_user("Alice", "alice@example.com")
    record, code = verification_service.create_pending_verification(db_session, user.id, user.email)

    for _ in range(verification_service.MAX_ATTEMPTS):
        assert verification_service.verify_code(db_session, record.token, "000000") is None

    # Even the real code no longer works - the pending attempt itself is gone.
    assert verification_service.verify_code(db_session, record.token, code) is None
    assert db_session.get(PendingVerification, record.token) is None


def test_unknown_token_is_rejected(db_session) -> None:
    assert verification_service.verify_code(db_session, "not-a-real-token", "123456") is None


def test_resend_cooldown_blocks_rapid_repeats(db_session, make_user) -> None:
    user = make_user("Alice", "alice@example.com")
    verification_service.create_pending_verification(db_session, user.id, user.email)

    with pytest.raises(verification_service.ResendCooldownError):
        verification_service.create_pending_verification(db_session, user.id, user.email)


def test_resend_verification_issues_a_different_code(db_session, make_user, monkeypatch) -> None:
    user = make_user("Alice", "alice@example.com")
    record, first_code = verification_service.create_pending_verification(
        db_session, user.id, user.email
    )
    # Bypass the resend cooldown for this test's second call - it's covered separately.
    verification_service._last_sent_at.clear()

    email, second_code = verification_service.resend_verification(db_session, record.token)

    assert email == user.email
    assert second_code != first_code
    # The old code no longer works, only the new one does.
    assert verification_service.verify_code(db_session, record.token, first_code) is None
    assert verification_service.verify_code(db_session, record.token, second_code) == user.id
