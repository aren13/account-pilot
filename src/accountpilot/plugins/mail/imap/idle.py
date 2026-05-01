"""IMAP IDLE listener — one asyncio task per (account, folder)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from accountpilot.plugins.mail.imap import ConnectionError as ImapConnectionError

if TYPE_CHECKING:
    from collections.abc import Callable

    from accountpilot.plugins.mail.imap.client import ImapClient

    # Legacy mailpilot config types; replace with accountpilot models in Task 12
    AccountConfig = Any
    SyncConfig = Any
    SyncEngine = Any

logger = logging.getLogger(__name__)


class IdleListener:
    """Monitor an IMAP folder via IDLE and trigger incremental sync.

    Each instance manages a single (account, folder) pair. It is
    designed to run as a long-lived :func:`asyncio.create_task` target
    via :meth:`run`.

    Args:
        imap_client: Connected :class:`ImapClient` for this account.
        sync_engine: :class:`SyncEngine` that handles downloads.
        account: Account configuration.
        folder: IMAP folder to watch (e.g. ``"INBOX"``).
        config: Sync configuration (timeouts, backoff).
        on_new_mail: Optional callback invoked with a list of new
            ``mp_id`` strings after each incremental sync.
    """

    def __init__(
        self,
        imap_client: ImapClient,
        sync_engine: SyncEngine,
        account: AccountConfig,
        folder: str,
        config: SyncConfig,
        on_new_mail: Callable[[list[str]], None] | None = None,
    ) -> None:
        self._imap = imap_client
        self._sync = sync_engine
        self._account = account
        self._folder = folder
        self._config = config
        self._on_new_mail = on_new_mail
        self._running = False
        self._highest_uid: int = 0

    # -- Public API -------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the IDLE loop is currently active."""
        return self._running

    async def run(self) -> None:
        """Core IDLE loop.

        1. Connect and SELECT the folder.
        2. Fetch the initial highest UID.
        3. Enter IDLE, wait for a server notification or timeout.
        4. On notification: break IDLE, incremental sync, callback.
        5. On timeout: break IDLE and re-enter.
        6. On connection error: backoff, reconnect, resume.
        """
        self._running = True
        delay = self._config.reconnect_base_delay

        while self._running:
            try:
                await self._imap.ensure_connected(self._folder)
                self._highest_uid = await self._get_highest_uid()
                delay = self._config.reconnect_base_delay
                await self._idle_loop()
            except (
                ImapConnectionError,
                OSError,
                TimeoutError,
            ) as exc:
                if not self._running:
                    break
                logger.warning(
                    "IDLE connection error for %s/%s: %s — "
                    "retrying in %ds",
                    self._account.name,
                    self._folder,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                delay = min(
                    delay * 2,
                    self._config.reconnect_max_delay,
                )
            except asyncio.CancelledError:
                logger.debug(
                    "IDLE task cancelled for %s/%s",
                    self._account.name,
                    self._folder,
                )
                break
            except Exception:
                if not self._running:
                    break
                logger.exception(
                    "Unexpected error in IDLE loop for %s/%s",
                    self._account.name,
                    self._folder,
                )
                await asyncio.sleep(delay)
                delay = min(
                    delay * 2,
                    self._config.reconnect_max_delay,
                )

        self._running = False
        logger.info(
            "IDLE listener stopped for %s/%s",
            self._account.name,
            self._folder,
        )

    async def stop(self) -> None:
        """Signal the IDLE loop to exit and disconnect."""
        self._running = False
        try:
            await self._imap.disconnect(self._folder)
        except Exception:
            logger.debug(
                "Error disconnecting %s/%s during stop (ignored)",
                self._account.name,
                self._folder,
            )

    # -- Private helpers --------------------------------------------

    async def _get_highest_uid(self) -> int:
        """Fetch the current highest UID in the folder."""
        uids = await self._imap.fetch_uids(self._folder)
        return max(uids) if uids else 0

    async def _idle_loop(self) -> None:
        """Enter and re-enter IDLE until stopped or disconnected."""
        while self._running:
            conn = self._imap._connections.get(self._folder)
            if conn is None:
                raise ImapConnectionError(
                    f"No connection for {self._folder}"
                )

            idle_timeout = self._config.idle_timeout
            logger.debug(
                "Entering IDLE for %s/%s (timeout=%ds)",
                self._account.name,
                self._folder,
                idle_timeout,
            )

            idle_fut = await conn.idle_start(timeout=idle_timeout)
            notification = await asyncio.wait_for(
                idle_fut, timeout=idle_timeout + 30
            )

            # Break out of IDLE
            conn.idle_done()

            if not self._running:
                break

            if self._has_new_mail(notification):
                await self._handle_new_mail()

    def _has_new_mail(self, idle_response: object) -> bool:
        """Determine if the IDLE response indicates new messages.

        aioimaplib returns response lines; we look for EXISTS or
        RECENT keywords.
        """
        if idle_response is None:
            return False

        lines: list[object]
        if hasattr(idle_response, "lines"):
            lines = idle_response.lines
        elif isinstance(idle_response, (list, tuple)):
            lines = list(idle_response)
        else:
            lines = [idle_response]

        for line in lines:
            text = str(line).upper()
            if "EXISTS" in text or "RECENT" in text:
                return True
        return False

    async def _handle_new_mail(self) -> None:
        """Run incremental sync and fire the callback."""
        start = time.monotonic()
        logger.info(
            "New mail detected for %s/%s, syncing from UID %d",
            self._account.name,
            self._folder,
            self._highest_uid,
        )

        try:
            new_mp_ids = await self._sync.incremental_sync(
                self._folder, self._highest_uid
            )
        except Exception:
            logger.exception(
                "Incremental sync failed for %s/%s",
                self._account.name,
                self._folder,
            )
            return

        # Update the high-water mark
        new_highest = await self._get_highest_uid()
        if new_highest > self._highest_uid:
            self._highest_uid = new_highest

        elapsed = time.monotonic() - start
        logger.info(
            "Synced %d new messages for %s/%s in %.1fs",
            len(new_mp_ids),
            self._account.name,
            self._folder,
            elapsed,
        )

        if new_mp_ids and self._on_new_mail is not None:
            try:
                self._on_new_mail(new_mp_ids)
            except Exception:
                logger.exception("on_new_mail callback error")
