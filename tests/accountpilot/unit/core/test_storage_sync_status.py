"""Tests for Storage.update_sync_status (sync_status table upsert)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path  # noqa: TC003 — runtime use in fixture signatures

import aiosqlite  # noqa: TC002 — runtime use in fixture signatures

from accountpilot.core.cas import CASStore
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage


async def _seed_account(storage: Storage) -> int:
    owner = await storage.upsert_owner(
        name="Aren", surname=None,
        identifiers=[Identifier(kind="email", value="a@b.com")],
    )
    return await storage.upsert_account(
        source="gmail", identifier="a@b.com", owner_id=owner,
    )


async def test_update_sync_status_inserts_on_first_call(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    aid = await _seed_account(storage)

    await storage.update_sync_status(aid, success=True, messages_added=42)

    async with tmp_db.execute(
        "SELECT last_sync_at, last_success_at, last_error, "
        "       last_error_at, messages_ingested "
        "FROM sync_status WHERE account_id=?",
        (aid,),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["last_sync_at"] is not None
    assert row["last_success_at"] is not None
    assert row["last_error"] is None
    assert row["last_error_at"] is None
    assert row["messages_ingested"] == 42


async def test_update_sync_status_increments_messages_ingested(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    aid = await _seed_account(storage)

    await storage.update_sync_status(aid, success=True, messages_added=5)
    await storage.update_sync_status(aid, success=True, messages_added=3)

    async with tmp_db.execute(
        "SELECT messages_ingested FROM sync_status WHERE account_id=?",
        (aid,),
    ) as cur:
        row = await cur.fetchone()
    assert row["messages_ingested"] == 8


async def test_update_sync_status_error_does_not_clear_last_success(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    aid = await _seed_account(storage)

    await storage.update_sync_status(aid, success=True, messages_added=1)

    async with tmp_db.execute(
        "SELECT last_success_at FROM sync_status WHERE account_id=?", (aid,)
    ) as cur:
        success_ts = (await cur.fetchone())["last_success_at"]

    await storage.update_sync_status(
        aid, success=False, error="ConnectionError: blip",
    )

    async with tmp_db.execute(
        "SELECT last_success_at, last_error, last_error_at "
        "FROM sync_status WHERE account_id=?",
        (aid,),
    ) as cur:
        row = await cur.fetchone()
    assert row["last_success_at"] == success_ts  # preserved
    assert row["last_error"] == "ConnectionError: blip"
    assert row["last_error_at"] is not None


async def test_update_sync_status_success_clears_previous_error(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    aid = await _seed_account(storage)

    await storage.update_sync_status(aid, success=False, error="boom")
    await storage.update_sync_status(aid, success=True, messages_added=0)

    async with tmp_db.execute(
        "SELECT last_error, last_error_at FROM sync_status WHERE account_id=?",
        (aid,),
    ) as cur:
        row = await cur.fetchone()
    assert row["last_error"] is None
    assert row["last_error_at"] is None


async def test_update_sync_status_failure_no_message_count_bump(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    aid = await _seed_account(storage)

    await storage.update_sync_status(aid, success=True, messages_added=10)
    await storage.update_sync_status(aid, success=False, error="oops")

    async with tmp_db.execute(
        "SELECT messages_ingested FROM sync_status WHERE account_id=?",
        (aid,),
    ) as cur:
        assert (await cur.fetchone())["messages_ingested"] == 10


# Sanity check that timestamps are tz-aware UTC ISO strings.
async def test_update_sync_status_timestamps_are_utc(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    aid = await _seed_account(storage)
    await storage.update_sync_status(aid, success=True, messages_added=0)
    async with tmp_db.execute(
        "SELECT last_sync_at FROM sync_status WHERE account_id=?", (aid,)
    ) as cur:
        ts = (await cur.fetchone())["last_sync_at"]
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == datetime.now(UTC).utcoffset()
