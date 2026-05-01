from __future__ import annotations

from typing import TYPE_CHECKING

from accountpilot.core.identity import find_or_create_person

if TYPE_CHECKING:
    import aiosqlite


async def test_creates_person_and_identifier(tmp_db: aiosqlite.Connection) -> None:
    pid = await find_or_create_person(
        tmp_db, kind="email", value="Foo@Bar.com", default_name="Foo Bar"
    )
    async with tmp_db.execute(
        "SELECT name, surname, is_owner FROM people WHERE id=?", (pid,)
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["name"] == "Foo"
    assert row["surname"] == "Bar"
    assert row["is_owner"] == 0
    async with tmp_db.execute(
        "SELECT person_id, kind, value FROM identifiers WHERE person_id=?", (pid,)
    ) as cur:
        rows = list(await cur.fetchall())
    assert len(rows) == 1
    assert rows[0]["kind"] == "email"
    assert rows[0]["value"] == "foo@bar.com"


async def test_returns_existing_person(tmp_db: aiosqlite.Connection) -> None:
    pid1 = await find_or_create_person(
        tmp_db, kind="email", value="x@y.com", default_name="X"
    )
    pid2 = await find_or_create_person(
        tmp_db, kind="email", value="X@Y.COM", default_name="someone else"
    )
    assert pid1 == pid2


async def test_normalizes_phone_before_lookup(tmp_db: aiosqlite.Connection) -> None:
    pid1 = await find_or_create_person(
        tmp_db, kind="phone", value="+90 505 249 01 39", default_name=None
    )
    pid2 = await find_or_create_person(
        tmp_db, kind="phone", value="+905052490139", default_name=None
    )
    assert pid1 == pid2


async def test_default_name_unknown_when_missing(
    tmp_db: aiosqlite.Connection,
) -> None:
    pid = await find_or_create_person(
        tmp_db, kind="email", value="anon@example.com", default_name=None
    )
    async with tmp_db.execute("SELECT name FROM people WHERE id=?", (pid,)) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["name"] == "Unknown"
