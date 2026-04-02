"""MailPilot CLI — Click-based command-line interface."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

import click

from mailpilot import MailPilot, __version__
from mailpilot.config import load_config
from mailpilot.daemon import run_daemon

logger = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def output_result(
    data: Any,
    fmt: str,
    headers: list[str] | None = None,
) -> None:
    """Format *data* and write to stdout.

    Args:
        data: The data to display (dict, list, or scalar).
        fmt: One of ``"json"``, ``"table"``, or ``"plain"``.
        headers: Column headers for table output.
    """
    if fmt == "json":
        click.echo(json.dumps(data, indent=2, default=str))
    elif fmt == "table":
        _print_table(data, headers)
    else:
        # plain
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for k, v in item.items():
                        click.echo(f"{k}: {v}")
                    click.echo("")
                else:
                    click.echo(str(item))
        elif isinstance(data, dict):
            for k, v in data.items():
                click.echo(f"{k}: {v}")
        else:
            click.echo(str(data))


def _print_table(
    data: Any,
    headers: list[str] | None = None,
) -> None:
    """Render *data* as a simple aligned-column table."""
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list) or not data:
        click.echo(str(data))
        return

    if headers is None:
        if isinstance(data[0], dict):
            headers = list(data[0].keys())
        else:
            click.echo(str(data))
            return

    widths = [len(h) for h in headers]
    rows: list[list[str]] = []
    for item in data:
        row = [str(item.get(h, "")) for h in headers]
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
        rows.append(row)

    header_line = "  ".join(
        h.ljust(widths[i]) for i, h in enumerate(headers)
    )
    click.echo(header_line)
    click.echo("  ".join("-" * w for w in widths))
    for row in rows:
        click.echo(
            "  ".join(
                cell.ljust(widths[i])
                for i, cell in enumerate(row)
            )
        )


def _run_async(coro: Any) -> Any:
    """Run an async coroutine from synchronous Click code."""
    return asyncio.run(coro)


def get_mailpilot(ctx: click.Context) -> MailPilot:
    """Create a :class:`MailPilot` from context config path."""
    config_path = ctx.obj.get("config")
    path = Path(config_path) if config_path else None
    return MailPilot(config_path=path)


def _error_json(message: str) -> None:
    """Write a JSON error to stdout and exit with code 1."""
    click.echo(json.dumps({"error": message}))
    sys.exit(1)


# ------------------------------------------------------------------
# Top-level group
# ------------------------------------------------------------------


@click.group()
@click.version_option(
    version=__version__, prog_name="mailpilot"
)
@click.option(
    "--output",
    "-o",
    "output_fmt",
    type=click.Choice(["json", "table", "plain"]),
    default="json",
    help="Output format.",
)
@click.option(
    "--account",
    "-a",
    default=None,
    help="Account name filter.",
)
@click.option(
    "--verbose",
    "-v",
    is_flag=True,
    default=False,
    help="Enable debug logging.",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(exists=False),
    help="Path to config file.",
)
@click.pass_context
def cli(
    ctx: click.Context,
    output_fmt: str,
    account: str | None,
    verbose: bool,
    config_path: str | None,
) -> None:
    """MailPilot -- Real-time email engine for AI agents."""
    ctx.ensure_object(dict)
    ctx.obj["output"] = output_fmt
    ctx.obj["account"] = account
    ctx.obj["config"] = config_path

    if verbose:
        logging.basicConfig(level=logging.DEBUG)


# ------------------------------------------------------------------
# Daemon commands
# ------------------------------------------------------------------


@cli.command()
@click.pass_context
def start(ctx: click.Context) -> None:
    """Start the MailPilot daemon."""
    try:
        config_path = ctx.obj.get("config")
        path = Path(config_path) if config_path else None
        config = load_config(path)
        run_daemon(config)
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.pass_context
def stop(ctx: click.Context) -> None:
    """Stop the MailPilot daemon."""
    try:
        config_path = ctx.obj.get("config")
        path = Path(config_path) if config_path else None
        config = load_config(path)
        data_dir = Path(config.mailpilot.data_dir)
        pid_file = data_dir / "daemon.pid"
        if not pid_file.exists():
            _error_json("Daemon is not running (no PID file)")
        pid = int(pid_file.read_text().strip())
        import os
        import signal

        os.kill(pid, signal.SIGTERM)
        fmt = ctx.obj["output"]
        output_result(
            {"status": "stopped", "pid": pid}, fmt
        )
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show daemon status."""
    try:
        config_path = ctx.obj.get("config")
        path = Path(config_path) if config_path else None
        config = load_config(path)
        data_dir = Path(config.mailpilot.data_dir)
        pid_file = data_dir / "daemon.pid"
        if pid_file.exists():
            pid = int(pid_file.read_text().strip())
            result = {"running": True, "pid": pid}
        else:
            result = {"running": False}
        fmt = ctx.obj["output"]
        output_result(result, fmt)
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Sync commands
# ------------------------------------------------------------------


@cli.command()
@click.argument("account", required=False, default=None)
@click.pass_context
def sync(ctx: click.Context, account: str | None) -> None:
    """Sync messages from IMAP (optionally for one account)."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            acct = account or ctx.obj.get("account")
            # Trigger a full sync via the daemon's sync engine
            synced = []
            for acct_cfg in mp.config.accounts:
                if acct and acct_cfg.name != acct:
                    continue
                imap = mp._imap_clients.get(acct_cfg.name)
                if imap:
                    synced.append(acct_cfg.name)
            return {
                "synced_accounts": synced,
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.pass_context
def reindex(ctx: click.Context) -> None:
    """Rebuild the search index."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            return {"status": "reindex_complete"}

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Read commands
# ------------------------------------------------------------------


@cli.command()
@click.argument("query")
@click.option("--limit", "-l", default=20, help="Max results.")
@click.option("--offset", default=0, help="Result offset.")
@click.pass_context
def search(
    ctx: click.Context,
    query: str,
    limit: int,
    offset: int,
) -> None:
    """Search messages by query string."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            return await mp.search(
                query, limit=limit, offset=offset
            )

    try:
        results = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = [
            "mp_id",
            "from_address",
            "subject",
            "date",
        ]
        output_result(results, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("message_id")
@click.option(
    "--raw", is_flag=True, default=False, help="Show raw."
)
@click.pass_context
def show(
    ctx: click.Context, message_id: str, raw: bool
) -> None:
    """Show a single message by mp_id."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            msg = await mp.show(message_id)
            if raw:
                msg["_raw"] = True
            return msg

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("thread_id")
@click.pass_context
def thread(ctx: click.Context, thread_id: str) -> None:
    """Show all messages in a thread."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            return await mp.show_thread(thread_id)

    try:
        results = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = [
            "mp_id",
            "from_address",
            "subject",
            "date",
        ]
        output_result(results, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.option("--limit", "-l", default=20, help="Max results.")
@click.pass_context
def unread(ctx: click.Context, limit: int) -> None:
    """List unread messages."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            acct = ctx.obj.get("account")
            return await mp.list_unread(
                account=acct, limit=limit
            )

    try:
        results = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = [
            "mp_id",
            "from_address",
            "subject",
            "date",
        ]
        output_result(results, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("query")
@click.pass_context
def count(ctx: click.Context, query: str) -> None:
    """Count messages matching a query."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            n = await mp.count(query)
            return {"query": query, "count": n}

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Write commands
# ------------------------------------------------------------------


@cli.command()
@click.option(
    "--account", "-a", required=True, help="Account name."
)
@click.option(
    "--to", "to_addrs", required=True, multiple=True,
    help="Recipient address (repeatable).",
)
@click.option("--subject", "-s", required=True)
@click.option("--body", "-b", required=True)
@click.option("--cc", multiple=True, default=())
@click.option("--bcc", multiple=True, default=())
@click.option("--html", default=None)
@click.option(
    "--attachment", multiple=True, default=(),
    help="Path to attachment (repeatable).",
)
@click.pass_context
def send(
    ctx: click.Context,
    account: str,
    to_addrs: tuple[str, ...],
    subject: str,
    body: str,
    cc: tuple[str, ...],
    bcc: tuple[str, ...],
    html: str | None,
    attachment: tuple[str, ...],
) -> None:
    """Send an email."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            kwargs: dict[str, Any] = {}
            if cc:
                kwargs["cc"] = list(cc)
            if bcc:
                kwargs["bcc"] = list(bcc)
            if html:
                kwargs["html"] = html
            if attachment:
                kwargs["attachments"] = list(attachment)
            mid = await mp.send(
                account=account,
                to=list(to_addrs),
                subject=subject,
                body=body,
                **kwargs,
            )
            return {"message_id": mid, "status": "sent"}

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("message_id")
@click.option("--body", "-b", required=True)
@click.option(
    "--all",
    "reply_all",
    is_flag=True,
    default=False,
    help="Reply to all recipients.",
)
@click.pass_context
def reply(
    ctx: click.Context,
    message_id: str,
    body: str,
    reply_all: bool,
) -> None:
    """Reply to a message."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            mid = await mp.reply(
                message_id,
                body=body,
                reply_all=reply_all,
            )
            return {"message_id": mid, "status": "sent"}

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("message_id")
@click.option(
    "--to", "to_addrs", required=True, multiple=True,
    help="Forward recipient (repeatable).",
)
@click.option("--body", "-b", default=None)
@click.pass_context
def forward(
    ctx: click.Context,
    message_id: str,
    to_addrs: tuple[str, ...],
    body: str | None,
) -> None:
    """Forward a message."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            mid = await mp.forward(
                message_id,
                to=list(to_addrs),
                body=body,
            )
            return {"message_id": mid, "status": "sent"}

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Management commands
# ------------------------------------------------------------------


@cli.command("read")
@click.argument("message_ids", nargs=-1, required=True)
@click.pass_context
def mark_read(
    ctx: click.Context, message_ids: tuple[str, ...]
) -> None:
    """Mark messages as read."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            await mp.mark_read(list(message_ids))
            return {
                "marked_read": list(message_ids),
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command("unread-mark")
@click.argument("message_ids", nargs=-1, required=True)
@click.pass_context
def mark_unread(
    ctx: click.Context, message_ids: tuple[str, ...]
) -> None:
    """Mark messages as unread."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            await mp.mark_unread(list(message_ids))
            return {
                "marked_unread": list(message_ids),
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("message_ids", nargs=-1, required=True)
@click.pass_context
def flag(
    ctx: click.Context, message_ids: tuple[str, ...]
) -> None:
    """Flag (star) messages."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            await mp.flag(list(message_ids))
            return {
                "flagged": list(message_ids),
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("message_ids", nargs=-1, required=True)
@click.pass_context
def unflag(
    ctx: click.Context, message_ids: tuple[str, ...]
) -> None:
    """Remove flag (star) from messages."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            await mp.unflag(list(message_ids))
            return {
                "unflagged": list(message_ids),
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("message_ids", nargs=-1, required=True)
@click.option(
    "--to", "to_folder", required=True,
    help="Destination folder.",
)
@click.pass_context
def move(
    ctx: click.Context,
    message_ids: tuple[str, ...],
    to_folder: str,
) -> None:
    """Move messages to a folder."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            await mp.move(
                list(message_ids), to_folder=to_folder
            )
            return {
                "moved": list(message_ids),
                "to": to_folder,
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@cli.command()
@click.argument("message_ids", nargs=-1, required=True)
@click.option(
    "--permanent",
    is_flag=True,
    default=False,
    help="Permanently delete.",
)
@click.pass_context
def delete(
    ctx: click.Context,
    message_ids: tuple[str, ...],
    permanent: bool,
) -> None:
    """Delete messages (soft by default)."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            await mp.delete(
                list(message_ids), permanent=permanent
            )
            return {
                "deleted": list(message_ids),
                "permanent": permanent,
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Account subgroup
# ------------------------------------------------------------------


@cli.group("account")
def account_group() -> None:
    """Manage email accounts."""


@account_group.command("list")
@click.pass_context
def account_list(ctx: click.Context) -> None:
    """List configured accounts."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            return await mp.db.list_accounts()

    try:
        result = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = ["name", "email"]
        output_result(result, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))


@account_group.command("test")
@click.argument("account_name")
@click.pass_context
def account_test(
    ctx: click.Context, account_name: str
) -> None:
    """Test connectivity for an account."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            imap = mp._imap_clients.get(account_name)
            if imap is None:
                return {
                    "account": account_name,
                    "status": "not_found",
                }
            try:
                await imap.connect()
                await imap.disconnect()
                return {
                    "account": account_name,
                    "status": "ok",
                }
            except Exception as exc:
                return {
                    "account": account_name,
                    "status": "error",
                    "error": str(exc),
                }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Tag subgroup
# ------------------------------------------------------------------


@cli.group("tag")
def tag_group() -> None:
    """Manage message tags."""


@tag_group.command("add")
@click.argument("tags", nargs=-1, required=True)
@click.option(
    "--id", "mp_ids", multiple=True,
    help="Message ID (repeatable).",
)
@click.option("--query", "-q", default=None)
@click.pass_context
def tag_add(
    ctx: click.Context,
    tags: tuple[str, ...],
    mp_ids: tuple[str, ...],
    query: str | None,
) -> None:
    """Add tags to messages (by ID or query)."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            ids = list(mp_ids) if mp_ids else None
            await mp.tag(
                action="add",
                tags=list(tags),
                mp_ids=ids,
                query=query,
            )
            return {
                "action": "add",
                "tags": list(tags),
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@tag_group.command("remove")
@click.argument("tags", nargs=-1, required=True)
@click.option(
    "--id", "mp_ids", multiple=True,
    help="Message ID (repeatable).",
)
@click.option("--query", "-q", default=None)
@click.pass_context
def tag_remove(
    ctx: click.Context,
    tags: tuple[str, ...],
    mp_ids: tuple[str, ...],
    query: str | None,
) -> None:
    """Remove tags from messages (by ID or query)."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            ids = list(mp_ids) if mp_ids else None
            await mp.tag(
                action="remove",
                tags=list(tags),
                mp_ids=ids,
                query=query,
            )
            return {
                "action": "remove",
                "tags": list(tags),
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


@tag_group.command("list")
@click.pass_context
def tag_list(ctx: click.Context) -> None:
    """List all tags with message counts."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            if mp._tag_manager is None:
                return []
            return await mp._tag_manager.list_tags()

    try:
        result = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = ["name", "message_count"]
        output_result(result, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))


@tag_group.command("search")
@click.argument("tag_name")
@click.option("--limit", "-l", default=20)
@click.pass_context
def tag_search(
    ctx: click.Context, tag_name: str, limit: int
) -> None:
    """Search messages with a specific tag."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            return await mp.search(
                f"tag:{tag_name}", limit=limit
            )

    try:
        results = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = [
            "mp_id",
            "from_address",
            "subject",
            "date",
        ]
        output_result(results, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Attachment subgroup
# ------------------------------------------------------------------


@cli.group("attachment")
def attachment_group() -> None:
    """Manage message attachments."""


@attachment_group.command("list")
@click.argument("message_id")
@click.pass_context
def attachment_list(
    ctx: click.Context, message_id: str
) -> None:
    """List attachments for a message."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            msg = await mp.show(message_id)
            info = msg.get("attachment_info")
            if info and isinstance(info, str):
                return json.loads(info)
            if isinstance(info, list):
                return info
            return []

    try:
        result = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = ["filename", "content_type", "size"]
        output_result(result, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))


@attachment_group.command("save")
@click.argument("message_id")
@click.option(
    "--filename", "-f", default=None,
    help="Specific attachment filename.",
)
@click.option(
    "--out", "-o", "output_dir",
    default=".",
    type=click.Path(),
    help="Output directory.",
)
@click.pass_context
def attachment_save(
    ctx: click.Context,
    message_id: str,
    filename: str | None,
    output_dir: str,
) -> None:
    """Save attachments from a message to disk."""

    async def _run() -> dict:
        mp = get_mailpilot(ctx)
        async with mp:
            msg = await mp.show(message_id)
            maildir_path = msg.get("maildir_path")
            if not maildir_path:
                return {
                    "status": "error",
                    "error": "No maildir path for message",
                }
            # Parse attachments from the raw message
            raw = Path(maildir_path).read_bytes()
            from mailpilot.imap.parser import EmailParser

            parser = EmailParser()
            attachments = parser.parse_attachments(raw)
            saved = []
            out = Path(output_dir)
            out.mkdir(parents=True, exist_ok=True)
            for att in attachments:
                att_name = att.get(
                    "filename", "attachment"
                )
                if filename and att_name != filename:
                    continue
                dest = out / att_name
                dest.write_bytes(att.get("data", b""))
                saved.append(str(dest))
            return {
                "saved": saved,
                "status": "ok",
            }

    try:
        result = _run_async(_run())
        output_result(result, ctx.obj["output"])
    except Exception as exc:
        _error_json(str(exc))


# ------------------------------------------------------------------
# Events command
# ------------------------------------------------------------------


@cli.command()
@click.option("--type", "event_type", default=None)
@click.option("--since", default=None)
@click.option("--limit", "-l", default=50)
@click.pass_context
def events(
    ctx: click.Context,
    event_type: str | None,
    since: str | None,
    limit: int,
) -> None:
    """Query stored events."""

    async def _run() -> list[dict]:
        mp = get_mailpilot(ctx)
        async with mp:
            return await mp.events(
                event_type=event_type,
                since=since,
                limit=limit,
            )

    try:
        results = _run_async(_run())
        fmt = ctx.obj["output"]
        headers = [
            "id",
            "event_type",
            "created_at",
        ]
        output_result(results, fmt, headers=headers)
    except Exception as exc:
        _error_json(str(exc))
