from __future__ import annotations

from pathlib import Path  # noqa: TC003 (used at runtime for fixture arguments)

from accountpilot.core.db.connection import open_db


async def test_open_db_applies_migrations_and_sets_pragmas(
    tmp_db_path: Path,
) -> None:
    async with open_db(tmp_db_path) as db:
        async with db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0].lower() == "wal"
        async with db.execute("PRAGMA foreign_keys") as cur:
            row = await cur.fetchone()
            assert row is not None
            assert row[0] == 1
        async with db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='people'"
        ) as cur:
            assert (await cur.fetchone()) is not None


async def test_open_db_idempotent_on_second_open(tmp_db_path: Path) -> None:
    async with open_db(tmp_db_path) as db:  # noqa: SIM117 (intentional separate opens to test idempotency)
        async with db.execute("SELECT MAX(version) FROM schema_version") as cur:
            row = await cur.fetchone()
            assert row is not None
            v1 = row[0]
    async with open_db(tmp_db_path) as db:  # noqa: SIM117 (intentional separate opens to test idempotency)
        async with db.execute("SELECT MAX(version) FROM schema_version") as cur:
            row = await cur.fetchone()
            assert row is not None
            v2 = row[0]
    assert v1 == v2
