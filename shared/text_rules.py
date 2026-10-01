"""Cleaning of names people choose (account, team, project names).

Strips invisible and control characters -- Unicode categories Cf (format:
zero-width spaces, right-to-left overrides, ...) and Cc (control) -- which
otherwise let two names that look identical on screen be different, or make
text appear reversed. Ordinary letters, accents and emoji are kept.
"""

import unicodedata


def clean_display_text(value: object) -> object:
    """Remove invisible/control characters and surrounding whitespace.

    Accepts any value and returns non-strings unchanged, so it can run as a
    Pydantic "before" validator and leave type errors to Pydantic.
    """
    if not isinstance(value, str):
        return value
    kept = "".join(ch for ch in value if unicodedata.category(ch) not in ("Cf", "Cc"))
    return kept.strip()
