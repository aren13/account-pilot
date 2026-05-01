"""accountpilot mail CLI subgroup."""

from __future__ import annotations

import asyncio
from collections.abc import (
    AsyncIterator,  # noqa: TC003 (used at runtime in async context manager return type)
)
from contextlib import asynccontextmanager
from pathlib import Path  # noqa: TC003 (used at runtime for path construction)
from typing import Any

import click

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.config import load_config
from accountpilot.core.db.connection import open_db
from accountpilot.core.storage import Storage
from accountpilot.plugins.mail.plugin import MailPlugin


@click.group("mail")
def mail_group() -> None:
    """Mail plugin commands (backfill, sync, daemon)."""


def _db_option(f: Any) -> Any:
    return click.option(
        "--db-path",
        type=click.Path(path_type=Path),
        default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
    )(f)


def _config_option(f: Any) -> Any:
    return click.option(
        "--config",
        "config_path",
        type=click.Path(path_type=Path),
        default=Path.home() / ".config" / "accountpilot" / "config.yaml",
    )(f)


@asynccontextmanager
async def _opened_plugin(
    config_path: Path, db_path: Path
) -> AsyncIterator[tuple[MailPlugin, Storage]]:
    """Open DB, build Storage + MailPlugin, yield. Closes DB on exit."""
    cfg = load_config(config_path)
    mail_cfg_raw = cfg.plugins.get("mail")
    if mail_cfg_raw is None or not mail_cfg_raw.enabled:
        raise click.UsageError(
            f"no enabled `plugins.mail` section in {config_path}"
        )
    mail_cfg_dict: dict[str, Any] = {
        "accounts": [a.model_dump() for a in mail_cfg_raw.accounts],
        **mail_cfg_raw.extra,
    }
    cas = CASStore(db_path.parent / "attachments")
    async with open_db(db_path) as db:
        storage = Storage(db, cas)
        plugin = MailPlugin(
            config=mail_cfg_dict, storage=storage, secrets=Secrets({})
        )
        yield plugin, storage


@mail_group.command("backfill")
@click.argument("account_id", type=int)
@_db_option
@_config_option
def mail_backfill(account_id: int, db_path: Path, config_path: Path) -> None:
    """One-shot historical pull for an account."""

    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, _):
            await plugin.setup()
            await plugin.backfill(account_id)

    asyncio.run(_run())
    click.echo(f"backfill complete: account={account_id}")


@mail_group.command("sync")
@click.argument("account_id", type=int)
@_db_option
@_config_option
def mail_sync(account_id: int, db_path: Path, config_path: Path) -> None:
    """One incremental sync pass."""

    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, _):
            await plugin.setup()
            await plugin.sync_once(account_id)

    asyncio.run(_run())
    click.echo(f"sync complete: account={account_id}")


@mail_group.command("daemon")
@_db_option
@_config_option
def mail_daemon(db_path: Path, config_path: Path) -> None:
    """Long-running daemon: polls all enabled mail accounts."""

    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, storage):
            await plugin.setup()
            # Look up enabled mail accounts from DB.
            async with storage.db.execute(
                "SELECT id FROM accounts WHERE source='gmail' AND enabled=1"
            ) as cur:
                rows = [r["id"] for r in await cur.fetchall()]
            if not rows:
                raise click.UsageError("no enabled gmail accounts in DB")
            # Run all in parallel.
            import asyncio as _asyncio

            await _asyncio.gather(*(plugin.daemon(aid) for aid in rows))

    asyncio.run(_run())
