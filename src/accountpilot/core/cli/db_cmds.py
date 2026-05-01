"""accountpilot db ..."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import click

from accountpilot.core.db.connection import open_db


@click.group("db")
def db_group() -> None:
    """Database management commands."""


@db_group.command("migrate")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def migrate(db_path: Path) -> None:
    """Apply pending migrations."""

    async def _run() -> None:
        async with open_db(db_path):
            pass  # open_db applies migrations.
        click.echo(f"migrated: {db_path}")

    asyncio.run(_run())


@db_group.command("vacuum")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def vacuum(db_path: Path) -> None:
    """Run SQLite VACUUM on the DB."""

    async def _run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("VACUUM")
        click.echo(f"vacuumed: {db_path}")

    asyncio.run(_run())
