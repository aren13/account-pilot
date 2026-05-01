from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(path: Path) -> None:
    path.write_text("""
version: 1
owners:
  - name: Aren
    surname: Eren
    identifiers:
      - { kind: email, value: aren@x.com }
      - { kind: phone, value: "+905052490139" }
plugins:
  mail:
    enabled: true
    accounts:
      - identifier: aren@x.com
        owner: aren@x.com
        provider: gmail
        credentials_ref: "op://x/y/z"
""")


def test_setup_creates_owner_and_account(tmp_path: Path, tmp_db_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0, result.output

    async def _check() -> None:
        async with open_db(tmp_db_path) as db:
            async with db.execute(
                "SELECT name FROM people WHERE is_owner=1"
            ) as cur:
                rows = [r["name"] for r in await cur.fetchall()]
            assert "Aren" in rows
            async with db.execute(
                "SELECT account_identifier FROM accounts"
            ) as cur:
                rows = [r["account_identifier"] for r in await cur.fetchall()]
            assert "aren@x.com" in rows
    asyncio.run(_check())


def test_setup_idempotent(tmp_path: Path, tmp_db_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg)
    runner = CliRunner()
    runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    result = runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0

    async def _check() -> None:
        async with open_db(tmp_db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) AS c FROM accounts"
            ) as cur:
                assert (await cur.fetchone())["c"] == 1  # type: ignore[index]
            async with db.execute(
                "SELECT COUNT(*) AS c FROM people WHERE is_owner=1"
            ) as cur:
                assert (await cur.fetchone())["c"] == 1  # type: ignore[index]
    asyncio.run(_check())


def test_setup_missing_owner_reference_errors(
    tmp_path: Path, tmp_db_path: Path
) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
version: 1
owners:
  - name: Aren
    surname: null
    identifiers:
      - { kind: email, value: aren@x.com }
plugins:
  mail:
    enabled: true
    accounts:
      - identifier: a@b.com
        owner: nobody@nowhere.com
        provider: gmail
""")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code != 0
    assert "owner" in result.output.lower()
