from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db

if TYPE_CHECKING:
    from pathlib import Path


def _seed(db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
                "VALUES ('Aren', 'E', 1, ?, ?)",
                (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
            )
            await db.execute(
                "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
                "created_at, updated_at) VALUES (1, 'gmail', 'a@b.com', 1, ?, ?)",
                (datetime.now(UTC).isoformat(), datetime.now(UTC).isoformat()),
            )
            await db.commit()
    asyncio.run(_run())


def test_status_lists_accounts(tmp_db_path: Path) -> None:
    _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0, result.output
    assert "gmail" in result.output
    assert "a@b.com" in result.output
    assert "Aren" in result.output


def test_status_empty_db(tmp_db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0
    assert "no accounts" in result.output.lower()
