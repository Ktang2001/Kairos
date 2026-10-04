"""Rules for account fields, shared so the client can check a form before
sending it and give the same answer the server would.

The server is still the authority -- it re-checks everything -- but checking
first means the user sees "Password must be at least 8 characters" instantly,
without a round trip to whichever computer is hosting.

The email check is deliberately permissive: it rejects obvious non-addresses
(no ``@``, embedded spaces) rather than attempting RFC 5322, because no regex
can prove an address is real; only delivering mail to it can.

Used by both the server and the client (shared/ is imported by each), so a
change here changes both at once -- keep it that way rather than copying
these values into either side.
"""

import re

#: Something@something.something, with no whitespace anywhere in it.
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Short enough that guessing is impractical, long enough not to be punitive.
#: The upper bound exists so an oversized body cannot be fed to the password
#: hasher -- hashing cost is dominated by the scrypt parameters, but there is
#: no reason to accept a megabyte of "password" either.
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 128

MAX_NAME_LENGTH = 100

#: RFC 5321 limits an email address to 254 characters.
MAX_EMAIL_LENGTH = 254

#: Passwords that meet the length rule but are among the first an attacker
#: tries. Not exhaustive -- no list can be -- but it stops the guesses that
#: succeed most often. Compared case-insensitively.
COMMON_PASSWORDS = frozenset(
    {
        "password",
        "password1",
        "password12",
        "password123",
        "password1234",
        "passw0rd",
        "p@ssw0rd",
        "p@ssword",
        "passw0rd1",
        "password!",
        "12345678",
        "123456789",
        "1234567890",
        "12341234",
        "11111111",
        "00000000",
        "87654321",
        "123123123",
        "12344321",
        "1q2w3e4r",
        "1qaz2wsx",
        "qwertyui",
        "qwerty123",
        "qwerty12",
        "qwertyuiop",
        "asdfghjk",
        "asdfasdf",
        "zxcvbnm1",
        "abcd1234",
        "abc12345",
        "abcdefgh",
        "iloveyou",
        "iloveyou1",
        "sunshine",
        "princess",
        "football",
        "baseball",
        "superman",
        "starwars",
        "whatever",
        "trustno1",
        "letmein1",
        "welcome1",
        "welcome123",
        "monkey12",
        "dragon12",
        "master12",
        "computer",
        "internet",
        "michelle",
        "jennifer",
        "corvette",
        "mustang1",
        "liverpool",
        "chelsea1",
        "changeme",
        "changeme1",
        "default1",
        "admin123",
        "administrator",
        "adminadmin",
        "letmein!",
        "qazwsxedc",
        "zaq12wsx",
        "q1w2e3r4",
        "q1w2e3r4t5",
        "1q2w3e4r5t",
        "access14",
        "shadow12",
        "michael1",
        "kairos123",
        "kairos2026",
        "technical",
        "difficulties",
    }
)


def password_problem(password: str, *, email: str = "", name: str = "") -> str | None:
    """Return why ``password`` is not acceptable, or None if it is.

    Used by the server (authoritative) and by the client's form check, so
    both give the same answer. Length is checked separately by the schema.
    """
    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        return "That password is too common. Choose something harder to guess."
    if len(set(password)) == 1:
        return "Password can't be one character repeated."
    email = email.strip().lower()
    local_part = email.split("@", 1)[0]
    if lowered in {email, local_part} - {""}:
        return "Password can't be your email address."
    if name.strip() and lowered == name.strip().lower():
        return "Password can't be your name."
    return None
