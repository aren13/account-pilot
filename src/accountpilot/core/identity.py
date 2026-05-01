"""Identity normalization, find-or-create, and merge logic."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import phonenumbers

if TYPE_CHECKING:
    import aiosqlite


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


async def find_or_create_person(
    db: aiosqlite.Connection,
    *,
    kind: str,
    value: str,
    default_name: str | None = None,
) -> int:
    """Look up the identifier; return person_id, creating both rows if absent."""
    if kind == "email":
        normalized = normalize_email(value)
    elif kind == "phone":
        normalized = normalize_phone(value)
    else:
        normalized = normalize_handle(value)

    async with db.execute(
        "SELECT person_id FROM identifiers WHERE kind=? AND value=?",
        (kind, normalized),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        return int(row["person_id"])

    name, surname = _split_display_name(default_name)
    now = datetime.now(UTC).isoformat()
    cur2 = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES (?, ?, 0, ?, ?)",
        (name, surname, now, now),
    )
    person_id = cur2.lastrowid
    assert person_id is not None
    await db.execute(
        "INSERT INTO identifiers (person_id, kind, value, is_primary, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (person_id, kind, normalized, now),
    )
    await db.commit()
    return person_id


def _split_display_name(name: str | None) -> tuple[str, str | None]:
    """Split 'Foo Bar' → ('Foo', 'Bar'); single token → ('Foo', None); missing
    → ('Unknown', None)."""
    if not name or not name.strip():
        return "Unknown", None
    parts = name.strip().split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]
