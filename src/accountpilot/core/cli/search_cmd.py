"""accountpilot search <query>"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from accountpilot.core.db.connection import open_db


@click.command("search")
@click.argument("query")
@click.option("--limit", type=int, default=20)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def search_cmd(query: str, limit: int, db_path: Path) -> None:
    """Full-text search over messages."""

    async def _run() -> None:
        async with open_db(db_path) as db, db.execute(
            """
            SELECT m.id, m.source, m.sent_at, COALESCE(ed.subject, '') AS subject,
                   SUBSTR(m.body_text, 1, 80) AS snippet
            FROM messages m
            JOIN messages_fts f ON f.rowid = m.id
            LEFT JOIN email_details ed ON ed.message_id = m.id
            WHERE messages_fts MATCH ?
            ORDER BY m.sent_at DESC
            LIMIT ?
            """,
            (query, limit),
        ) as cur:
            rows = await cur.fetchall()
        if not rows:
            click.echo("no matches.")
            return
        for r in rows:
            label = r["subject"] or r["snippet"]
            click.echo(f"[{r['source']}] {r['sent_at']}  {label}  (id={r['id']})")

    asyncio.run(_run())
