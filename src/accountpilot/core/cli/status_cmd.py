"""accountpilot status"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from accountpilot.core.db.connection import open_db


@click.command("status")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def status_cmd(db_path: Path) -> None:
    """Per-account health summary."""

    async def _run() -> None:
        async with open_db(db_path) as db, db.execute(
            """
            SELECT a.id, a.source, a.account_identifier, a.enabled,
                   p.name || COALESCE(' ' || p.surname, '') AS owner_name,
                   (SELECT COUNT(*) FROM messages m WHERE m.account_id=a.id)
                     AS msg_count,
                   s.last_sync_at, s.last_error
            FROM accounts a
            JOIN people p ON p.id = a.owner_id
            LEFT JOIN sync_status s ON s.account_id = a.id
            ORDER BY a.id
            """
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            click.echo("no accounts.")
            return
        for r in rows:
            enabled = "on" if r["enabled"] else "off"
            click.echo(
                f"#{r['id']} [{enabled}] {r['source']:<10}  "
                f"{r['account_identifier']:<30} "
                f"owner={r['owner_name']!r}  messages={r['msg_count']}  "
                f"last_sync={r['last_sync_at'] or '—'}  "
                f"last_error={r['last_error'] or '—'}"
            )

    asyncio.run(_run())
