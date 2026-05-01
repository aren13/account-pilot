"""Identity normalization, find-or-create, and merge logic."""

from __future__ import annotations

import phonenumbers


def normalize_email(raw: str) -> str:
    """Lowercase, strip whitespace, drop a `mailto:` prefix."""
    s = raw.strip()
    if s.lower().startswith("mailto:"):
        s = s[len("mailto:"):]
    return s.strip().lower()


def normalize_phone(raw: str, *, default_region: str | None = None) -> str:
    """Best-effort E.164 normalization. Returns stripped raw if unparseable."""
    s = raw.strip()
    try:
        parsed = phonenumbers.parse(s, default_region)
    except phonenumbers.NumberParseException:
        return s
    if not phonenumbers.is_possible_number(parsed):
        return s
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_handle(raw: str) -> str:
    """Dispatch by shape.

    Phone-like → E.164, email-like → lowercase, else lowercase strip.
    """
    s = raw.strip()
    if "@" in s:
        return normalize_email(s)
    if s.startswith("+") or s.replace(" ", "").replace("-", "").isdigit():
        normalized = normalize_phone(s)
        if normalized != s:
            return normalized
    return s.lower()
