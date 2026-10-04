from typing import ClassVar

import pytest

from server import email_sender

# tests/server/conftest.py's autouse `sent_codes` fixture monkeypatches
# `email_sender.send_verification_code` for every test (so nothing ever opens a
# real SMTP connection) - these tests are specifically about that real function's
# own internals, so they call this captured reference directly rather than going
# through the (stubbed) module attribute.
_real_send_verification_code = email_sender.send_verification_code


def test_raises_when_smtp_env_vars_are_missing(monkeypatch) -> None:
    monkeypatch.delenv("KAIROS_SMTP_USER", raising=False)
    monkeypatch.delenv("KAIROS_SMTP_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="KAIROS_SMTP_USER"):
        _real_send_verification_code("alice@example.com", "123456")


class _FakeSmtp:
    """Stands in for smtplib.SMTP_SSL - records what the real send code does
    with it rather than opening a real connection."""

    instances: ClassVar[list["_FakeSmtp"]] = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.login_calls: list[tuple[str, str]] = []
        self.sendmail_calls: list[tuple[str, list[str], str]] = []
        _FakeSmtp.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False

    def login(self, user, password):
        self.login_calls.append((user, password))

    def sendmail(self, from_addr, to_addrs, message):
        self.sendmail_calls.append((from_addr, to_addrs, message))


def test_sends_via_smtp_ssl_with_the_configured_credentials(monkeypatch) -> None:
    monkeypatch.setenv("KAIROS_SMTP_USER", "host@gmail.com")
    monkeypatch.setenv("KAIROS_SMTP_PASSWORD", "an-app-password")
    _FakeSmtp.instances = []
    monkeypatch.setattr(email_sender.smtplib, "SMTP_SSL", _FakeSmtp)

    _real_send_verification_code("alice@example.com", "654321")

    assert len(_FakeSmtp.instances) == 1
    smtp = _FakeSmtp.instances[0]
    assert smtp.host == email_sender.SMTP_HOST
    assert smtp.port == email_sender.SMTP_PORT
    assert smtp.login_calls == [("host@gmail.com", "an-app-password")]

    assert len(smtp.sendmail_calls) == 1
    from_addr, to_addrs, message = smtp.sendmail_calls[0]
    assert from_addr == "host@gmail.com"
    assert to_addrs == ["alice@example.com"]
    assert "654321" in message
