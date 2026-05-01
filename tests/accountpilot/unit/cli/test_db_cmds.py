from __future__ import annotations

from typing import TYPE_CHECKING

from click.testing import CliRunner

from accountpilot.cli import cli

if TYPE_CHECKING:
    from pathlib import Path


def test_db_migrate_creates_db_and_runs(tmp_db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["db", "migrate", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0, result.output
    assert tmp_db_path.exists()


def test_db_vacuum_runs(tmp_db_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["db", "migrate", "--db-path", str(tmp_db_path)])
    result = runner.invoke(cli, ["db", "vacuum", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0, result.output
