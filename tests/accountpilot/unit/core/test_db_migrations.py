from __future__ import annotations

from pathlib import Path  # noqa: TC003 (used at runtime for path construction)

import aiosqlite  # noqa: TC002 (used at runtime in function signatures)

from accountpilot.core.db.migrations import apply_migrations, current_version


async def _table_exists(db: aiosqlite.Connection, name: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ) as cur:
        return (await cur.fetchone()) is not None


async def test_apply_migrations_creates_schema_version_and_applies_files(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY);"
    )
    (migrations_dir / "002_second.sql").write_text(
        "CREATE TABLE beta (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)
        assert await _table_exists(db, "schema_version")
        assert await _table_exists(db, "alpha")
        assert await _table_exists(db, "beta")
        assert await current_version(db) == 2


async def test_apply_migrations_is_idempotent(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)
        await apply_migrations(db, migrations_dir)  # second run, no error
        assert await current_version(db) == 1


async def test_apply_migrations_only_applies_new(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)

    (migrations_dir / "002_second.sql").write_text(
        "CREATE TABLE beta (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)
        assert await current_version(db) == 2
        assert await _table_exists(db, "alpha")
        assert await _table_exists(db, "beta")
