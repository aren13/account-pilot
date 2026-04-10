"""MailPilot daemon — IDLE listeners and periodic sync orchestrator."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time
from pathlib import Path
from typing import TYPE_CHECKING

from mailpilot.database import Database
from mailpilot.imap.client import ImapClient
from mailpilot.imap.idle import IdleListener
from mailpilot.imap.parser import EmailParser
from mailpilot.imap.sync import MaildirManager, SyncEngine

if TYPE_CHECKING:
    from mailpilot.config import MailPilotConfig

logger = logging.getLogger(__name__)


class MailPilotDaemon:
    """Long-running daemon that watches IMAP folders via IDLE.

    Manages the lifecycle of :class:`IdleListener` tasks (one per
    account/folder pair), a periodic full-sync safety net, and the
    shared :class:`~mailpilot.database.Database`.

    Args:
        config: Fully loaded :class:`MailPilotConfig`.
    """

    def __init__(self, config: MailPilotConfig) -> None:
        self._config = config
        self._db: Database | None = None
        self._clients: dict[str, ImapClient] = {}
        self._engines: dict[str, SyncEngine] = {}
        self._listeners: dict[str, IdleListener] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._periodic_task: asyncio.Task[None] | None = None
        self._start_time: float | None = None

    # -- Public API -------------------------------------------------

    @property
    def config(self) -> MailPilotConfig:
        """The daemon's configuration."""
        return self._config

    async def start(self) -> None:
        """Boot the daemon.

        1. Initialize the database.
        2. For each account: create client, sync engine, run
           initial full sync.
        3. For each (account, folder) in the watch list: launch an
           :class:`IdleListener` as an asyncio task.
        4. Start the periodic full-sync safety-net task.
        5. Write a PID file to ``data_dir/daemon.pid``.
        """
        self._start_time = time.monotonic()
        data_dir = Path(self._config.mailpilot.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        # Set data_dir for OAuth token cache in IMAP/SMTP clients.
        import mailpilot.imap.client as _imap_mod
        import mailpilot.smtp.client as _smtp_mod

        _imap_mod._data_dir = str(data_dir)
        _smtp_mod._data_dir = str(data_dir)

        # Database
        db_path = data_dir / "mailpilot.db"
        self._db = Database(db_path)
        await self._db.initialize()
        logger.info("Database ready at %s", db_path)

        # Per-account setup
        maildir_base = data_dir / "maildir"
        parser = EmailParser()

        for acct_cfg in self._config.accounts:
            name = acct_cfg.name
            sync_cfg = self._config.sync

            client = ImapClient(acct_cfg, sync_cfg)
            self._clients[name] = client

            maildir = MaildirManager(maildir_base)
            engine = SyncEngine(
                client, self._db, maildir, parser, acct_cfg
            )
            self._engines[name] = engine

            # Initial full sync
            try:
                await engine.sync_account()
            except Exception:
                logger.exception(
                    "Initial sync failed for account %s", name
                )

            # Launch IDLE listeners for watched folders
            for folder in acct_cfg.folders.watch:
                key = f"{name}/{folder}"
                listener = IdleListener(
                    imap_client=client,
                    sync_engine=engine,
                    account=acct_cfg,
                    folder=folder,
                    config=sync_cfg,
                )
                self._listeners[key] = listener
                task = asyncio.create_task(
                    listener.run(), name=f"idle-{key}"
                )
                self._tasks[key] = task
                logger.info("IDLE listener started for %s", key)

        # Periodic full-sync safety net
        self._periodic_task = asyncio.create_task(
            self._periodic_sync(), name="periodic-sync"
        )

        # PID file
        self._write_pid(data_dir)
        logger.info(
            "MailPilot daemon started — %d account(s), "
            "%d listener(s)",
            len(self._config.accounts),
            len(self._listeners),
        )

    async def stop(self) -> None:
        """Gracefully shut down the daemon.

        1. Cancel the periodic sync task.
        2. Stop all IDLE listeners.
        3. Cancel listener tasks.
        4. Disconnect all IMAP clients.
        5. Close the database.
        6. Remove the PID file.
        """
        logger.info("Stopping MailPilot daemon...")

        # Cancel periodic sync
        if self._periodic_task is not None:
            self._periodic_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._periodic_task
            self._periodic_task = None

        # Stop listeners
        for key, listener in self._listeners.items():
            logger.debug("Stopping listener %s", key)
            await listener.stop()

        # Cancel tasks
        for _key, task in self._tasks.items():
            if not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._tasks.clear()
        self._listeners.clear()

        # Disconnect IMAP clients
        for name, client in self._clients.items():
            try:
                await client.disconnect()
            except Exception:
                logger.debug(
                    "Error disconnecting client %s (ignored)",
                    name,
                )
        self._clients.clear()
        self._engines.clear()

        # Close database
        if self._db is not None:
            await self._db.close()
            self._db = None

        # Remove PID file
        self._remove_pid()
        logger.info("MailPilot daemon stopped")

    async def status(self) -> dict:
        """Return a snapshot of daemon health.

        Returns:
            A dict with keys ``accounts``, ``listeners``,
            ``uptime_seconds``, and ``database_ready``.
        """
        uptime = (
            time.monotonic() - self._start_time
            if self._start_time is not None
            else 0.0
        )
        listener_info: dict[str, bool] = {}
        for key, listener in self._listeners.items():
            listener_info[key] = listener.is_running

        return {
            "accounts": [a.name for a in self._config.accounts],
            "listeners": listener_info,
            "uptime_seconds": round(uptime, 1),
            "database_ready": self._db is not None,
        }

    # -- Private helpers --------------------------------------------

    async def _periodic_sync(self) -> None:
        """Run full sync for all accounts on a fixed interval."""
        interval = self._config.sync.full_sync_interval
        logger.info(
            "Periodic sync task started (interval=%ds)", interval
        )
        while True:
            await asyncio.sleep(interval)
            logger.info("Running periodic full sync")
            for name, engine in self._engines.items():
                try:
                    await engine.sync_account()
                except Exception:
                    logger.exception(
                        "Periodic sync failed for %s", name
                    )

    def _write_pid(self, data_dir: Path) -> None:
        """Write current PID to ``data_dir/daemon.pid``."""
        pid_path = data_dir / "daemon.pid"
        pid_path.write_text(str(os.getpid()), encoding="utf-8")
        logger.debug("PID file written: %s", pid_path)

    def _remove_pid(self) -> None:
        """Remove the PID file if it exists."""
        pid_path = (
            Path(self._config.mailpilot.data_dir) / "daemon.pid"
        )
        try:
            pid_path.unlink(missing_ok=True)
        except OSError:
            logger.debug("Failed to remove PID file (ignored)")


# -------------------------------------------------------------------
# Module-level entry point
# -------------------------------------------------------------------


def run_daemon(config: MailPilotConfig) -> None:
    """Start the daemon with proper signal handling.

    Installs handlers for ``SIGTERM`` and ``SIGINT`` that trigger a
    graceful shutdown via :meth:`MailPilotDaemon.stop`.

    Args:
        config: Validated :class:`MailPilotConfig`.
    """
    daemon = MailPilotDaemon(config)

    async def _main() -> None:
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()

        def _signal_handler() -> None:
            logger.info("Received shutdown signal")
            stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, _signal_handler)

        await daemon.start()

        # Wait until a signal arrives
        await stop_event.wait()
        await daemon.stop()

    asyncio.run(_main())
