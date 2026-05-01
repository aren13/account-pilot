from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path  # noqa: TC003 (used at runtime in fixture signatures)

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db


def _seed(db_path: Path) -> int:
    async def _run() -> int:
        async with open_db(db_path) as db:
            await db.execute(
                "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
                "VALUES ('Aren', NULL, 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            cur = await db.execute(
                "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
                "created_at, updated_at) VALUES (1, 'gmail', 'a@b.com', 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            await db.commit()
            assert cur.lastrowid is not None
            return cur.lastrowid
    return asyncio.run(_run())


def test_list_accounts(tmp_db_path: Path) -> None:
    _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["accounts", "list", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0
    assert "a@b.com" in result.output


def test_disable_account(tmp_db_path: Path) -> None:
    aid = _seed(tmp_db_path)
    runner = CliRunner()
    runner.invoke(cli, [
        "accounts", "disable", str(aid), "--db-path", str(tmp_db_path),
    ])
    out = runner.invoke(cli, [
        "accounts", "list", "--db-path", str(tmp_db_path),
    ]).output
    assert "[off]" in out


def test_delete_account_with_force(tmp_db_path: Path) -> None:
    aid = _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "accounts", "delete", str(aid), "--force",
        "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0
    out = runner.invoke(cli, [
        "accounts", "list", "--db-path", str(tmp_db_path),
    ]).output
    assert "a@b.com" not in out


def test_delete_without_force_aborts(tmp_db_path: Path) -> None:
    aid = _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "accounts", "delete", str(aid),
        "--db-path", str(tmp_db_path),
    ], input="n\n")
    assert "aborted" in result.output.lower()
