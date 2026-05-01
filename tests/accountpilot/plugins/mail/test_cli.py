"""Mail plugin CLI tests."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 (used at runtime in function signature)

from click.testing import CliRunner

from accountpilot.cli import cli


def test_mail_subgroup_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["mail", "--help"])
    assert result.exit_code == 0
    assert "backfill" in result.output
    assert "sync" in result.output
    assert "daemon" in result.output


def test_mail_sync_runs_against_unconfigured_db_errors_cleanly(
    tmp_db_path: Path,
) -> None:
    """sync against a DB with no mail config should fail fast, not crash."""
    runner = CliRunner()
    missing_cfg = tmp_db_path.parent / "no-such-config.yaml"
    result = runner.invoke(
        cli,
        [
            "mail",
            "sync",
            "1",
            "--db-path",
            str(tmp_db_path),
            "--config",
            str(missing_cfg),
        ],
    )
    assert result.exit_code != 0
