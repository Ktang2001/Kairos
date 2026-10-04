"""Sends the 2FA verification code email (see server/services/verification_service.py).

Stdlib only (smtplib/email) - zero new dependencies. Requires the hosting
teammate to set two environment variables before starting the server:

    KAIROS_SMTP_USER       a Gmail address
    KAIROS_SMTP_PASSWORD   an App Password for that address (NOT the normal
                           account password - Gmail only accepts SMTP logins
                           via an App Password, which itself requires that
                           Google account to have 2-Step Verification turned
                           on first: https://myaccount.google.com/apppasswords)

This is the one function tests and local verification monkeypatch instead of
sending real mail - see tests/server/conftest.py's `sent_codes` fixture.
"""

import os
import smtplib
from email.mime.text import MIMEText

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_verification_code(to_email: str, code: str) -> None:
    user = os.environ.get("KAIROS_SMTP_USER")
    password = os.environ.get("KAIROS_SMTP_PASSWORD")
    if not user or not password:
        raise RuntimeError(
            "KAIROS_SMTP_USER and KAIROS_SMTP_PASSWORD must be set on the host "
            "to send verification emails - see server/email_sender.py"
        )

    message = MIMEText(
        f"Your Kairos verification code is: {code}\n\nThis code expires in 10 minutes."
    )
    message["Subject"] = "Your Kairos verification code"
    message["From"] = user
    message["To"] = to_email

    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
        smtp.login(user, password)
        smtp.sendmail(user, [to_email], message.as_string())
