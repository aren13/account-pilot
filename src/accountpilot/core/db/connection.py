"""SQLite connection setup for AccountPilot.

`open_db(path)` is the single entrypoint used by Storage and the CLI to
obtain an aiosqlite.Connection with the right pragmas and an up-to-date
schema. It is an async context manager.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

import aiosqlite

from accountpilot.core.db.migrations import apply_migrations

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


@asynccontextmanager
async def open_db(path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Open a SQLite DB at `path`, apply pending migrations, yield the connection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    try:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        db.row_factory = aiosqlite.Row
        await apply_migrations(db, _MIGRATIONS_DIR)
        yield db
    finally:
        await db.close()
