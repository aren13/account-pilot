from __future__ import annotations

from pathlib import Path  # noqa: TC003 (used at runtime for path construction)

import aiosqlite  # noqa: TC002 (used at runtime in function signatures)
import pytest

import accountpilot.core.db.migrations as _migrations_pkg  # noqa: E402
from accountpilot.core.db.migrations import apply_migrations, current_version

PROJECT_MIGRATIONS_DIR = Path(_migrations_pkg.__file__).parent


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


async def _columns(db: aiosqlite.Connection, table: str) -> list[str]:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        return [row[1] for row in await cur.fetchall()]


async def test_001_init_creates_all_tables(tmp_db_path: Path) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        for table in [
            "people",
            "identifiers",
            "accounts",
            "messages",
            "email_details",
            "imessage_details",
            "message_people",
            "attachments",
            "messages_fts",
            "sync_status",
        ]:
            assert await _table_exists(db, table), f"missing table: {table}"


async def test_001_init_people_columns(tmp_db_path: Path) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        cols = await _columns(db, "people")
    assert {"id", "name", "surname", "is_owner", "notes",
            "created_at", "updated_at"} <= set(cols)


async def test_001_init_unique_identifier(tmp_db_path: Path) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        await db.execute(
            "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
            "VALUES ('A', NULL, 0, '2026-05-01', '2026-05-01')"
        )
        await db.execute(
            "INSERT INTO identifiers "
            "(person_id, kind, value, is_primary, created_at) "
            "VALUES (1, 'email', 'x@y.com', 0, '2026-05-01')"
        )
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO identifiers "
                "(person_id, kind, value, is_primary, created_at) "
                "VALUES (1, 'email', 'x@y.com', 0, '2026-05-01')"
            )


async def test_001_init_fts_trigger_indexes_body_and_subject(
    tmp_db_path: Path,
) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        # Set up minimal owner+account so we can insert a message.
        await db.executescript("""
            INSERT INTO people (name, surname, is_owner, created_at, updated_at)
              VALUES ('Aren', 'E', 1, '2026-05-01', '2026-05-01');
            INSERT INTO accounts (
              owner_id, source, account_identifier, enabled, created_at, updated_at
            ) VALUES (1, 'gmail', 'a@b.com', 1, '2026-05-01', '2026-05-01');
            INSERT INTO messages (
              account_id, source, external_id, sent_at, body_text,
              direction, created_at
            ) VALUES (
              1, 'gmail', 'mid-1', '2026-05-01', 'lorem ipsum dolor',
              'inbound', '2026-05-01'
            );
            INSERT INTO email_details (
              message_id, subject, imap_uid, mailbox
            ) VALUES (1, 'Hello world', 42, 'INBOX');
        """)
        await db.commit()
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'lorem'"
        ) as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 1
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'world'"
        ) as cur:
            row = await cur.fetchone()
            assert row is not None and row[0] == 1
        # Update subject and verify email_details update trigger keeps FTS in sync.
        await db.execute(
            "UPDATE email_details SET subject = 'farewell cruel earth'"
            " WHERE message_id = 1"
        )
        await db.commit()
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'farewell'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1
        # The old subject term ('world') should no longer match.
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'world'"
        ) as cur:
            assert (await cur.fetchone()) is None
