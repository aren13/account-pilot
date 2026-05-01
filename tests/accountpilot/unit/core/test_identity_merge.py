from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from accountpilot.core.identity import find_or_create_person, merge_people

if TYPE_CHECKING:
    import aiosqlite


async def _seed_owner(db: aiosqlite.Connection, name: str) -> int:
    cur = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES (?, NULL, 1, ?, ?)",
        (name, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    pid = cur.lastrowid
    assert pid is not None
    await db.commit()
    return pid


async def test_merge_repoints_identifiers(tmp_db: aiosqlite.Connection) -> None:
    keep = await find_or_create_person(
        tmp_db, kind="email", value="keep@x.com", default_name="K"
    )
    discard = await find_or_create_person(
        tmp_db, kind="email", value="discard@x.com", default_name="D"
    )
    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute(
        "SELECT person_id FROM identifiers WHERE value=?", ("discard@x.com",)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["person_id"] == keep


async def test_merge_deletes_discarded_person(tmp_db: aiosqlite.Connection) -> None:
    keep = await find_or_create_person(
        tmp_db, kind="email", value="a@b.com", default_name="A"
    )
    discard = await find_or_create_person(
        tmp_db, kind="email", value="c@d.com", default_name="C"
    )
    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute(
        "SELECT 1 FROM people WHERE id=?", (discard,)
    ) as cur:
        assert (await cur.fetchone()) is None


async def test_merge_repoints_message_people(
    tmp_db: aiosqlite.Connection,
) -> None:
    owner = await _seed_owner(tmp_db, "owner")
    keep = await find_or_create_person(
        tmp_db, kind="email", value="k@x", default_name="K"
    )
    discard = await find_or_create_person(
        tmp_db, kind="email", value="d@x", default_name="D"
    )
    await tmp_db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'gmail', 'a@b.com', 1, ?, ?)",
        (owner, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    await tmp_db.execute(
        "INSERT INTO messages (account_id, source, external_id, sent_at, "
        "body_text, direction, created_at) VALUES (1, 'gmail', 'mid', ?, '', "
        "'inbound', ?)",
        (datetime.now().isoformat(), datetime.now().isoformat()),
    )
    await tmp_db.execute(
        "INSERT INTO message_people (message_id, person_id, role) "
        "VALUES (1, ?, 'from')",
        (discard,),
    )
    await tmp_db.commit()

    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute(
        "SELECT person_id FROM message_people WHERE message_id=1"
    ) as cur:
        rows = await cur.fetchall()
    assert [r["person_id"] for r in rows] == [keep]


async def test_merge_repoints_account_owner(tmp_db: aiosqlite.Connection) -> None:
    keep = await _seed_owner(tmp_db, "keeper")
    discard = await _seed_owner(tmp_db, "discarder")
    await tmp_db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'gmail', 'a@b.com', 1, ?, ?)",
        (discard, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    await tmp_db.commit()

    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute("SELECT owner_id FROM accounts WHERE id=1") as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["owner_id"] == keep


async def test_merge_rejects_self_merge(tmp_db: aiosqlite.Connection) -> None:
    keep = await find_or_create_person(
        tmp_db, kind="email", value="x@y", default_name="X"
    )
    with pytest.raises(ValueError):
        await merge_people(tmp_db, keep_id=keep, discard_id=keep)
