from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from click.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db
from accountpilot.core.identity import find_or_create_person


def _seed_two_people(db_path: Path) -> tuple[int, int]:
    async def _run() -> tuple[int, int]:
        async with open_db(db_path) as db:
            a = await find_or_create_person(
                db, kind="email", value="a@x.com", default_name="A"
            )
            b = await find_or_create_person(
                db, kind="email", value="b@x.com", default_name="B"
            )
            return a, b
    return asyncio.run(_run())


def test_list_people(tmp_db_path: Path) -> None:
    _seed_two_people(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["people", "list", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0
    assert "a@x.com" in result.output
    assert "b@x.com" in result.output


def test_show_person(tmp_db_path: Path) -> None:
    a, _ = _seed_two_people(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["people", "show", str(a), "--db-path", str(tmp_db_path)]
    )
    assert result.exit_code == 0
    assert "a@x.com" in result.output


def test_promote_demote_flips_owner_flag(tmp_db_path: Path) -> None:
    a, _ = _seed_two_people(tmp_db_path)
    runner = CliRunner()
    runner.invoke(cli, ["people", "promote", str(a), "--db-path", str(tmp_db_path)])
    out = runner.invoke(
        cli, ["people", "show", str(a), "--db-path", str(tmp_db_path)]
    ).output
    assert "owner: yes" in out
    runner.invoke(cli, ["people", "demote", str(a), "--db-path", str(tmp_db_path)])
    out = runner.invoke(
        cli, ["people", "show", str(a), "--db-path", str(tmp_db_path)]
    ).output
    assert "owner: no" in out


def test_merge_repoints_and_deletes(tmp_db_path: Path) -> None:
    a, b = _seed_two_people(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "people", "merge", "--keep", str(a), "--discard", str(b),
        "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0
    out = runner.invoke(cli, ["people", "list", "--db-path", str(tmp_db_path)]).output
    assert "b@x.com" in out  # identifier survives
    # Show discarded id should fail.
    show = runner.invoke(
        cli, ["people", "show", str(b), "--db-path", str(tmp_db_path)]
    )
    assert "not found" in show.output.lower()
