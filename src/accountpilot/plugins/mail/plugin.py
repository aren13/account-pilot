"""MailPlugin — implements the 5-hook AccountPilotPlugin contract for mail."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, ClassVar

from accountpilot.core.auth import Secrets  # noqa: TC001 - needed for __init__
from accountpilot.core.plugin import AccountPilotPlugin
from accountpilot.plugins.mail.config import (
    MailAccountConfig,
    MailPluginConfig,
)
from accountpilot.plugins.mail.imap.client import ImapClient
from accountpilot.plugins.mail.sync import sync_account_mailbox

log = logging.getLogger(__name__)

# Hardcoded provider hosts. SP3 may move these onto the Provider classes.
_PROVIDER_HOSTS: dict[str, tuple[str, int]] = {
    "gmail": ("imap.gmail.com", 993),
    "outlook": ("outlook.office365.com", 993),
}


class MailPlugin(AccountPilotPlugin):
    """Mail source plugin: IMAP fetch + IDLE."""

    name: ClassVar[str] = "mail"

    def __init__(
        self, config: dict[str, Any], storage: Any, secrets: Secrets
    ) -> None:
        super().__init__(config=config, storage=storage, secrets=secrets)
        self._cfg = MailPluginConfig.model_validate(config)
        # Map of account_identifier → MailAccountConfig for lookups.
        self._accounts: dict[str, MailAccountConfig] = {
            a.identifier: a for a in self._cfg.accounts
        }
        # Test seam: tests override to inject FakeImapClient.
        self._imap_factory = self._make_real_imap

    def _make_real_imap(self, account: MailAccountConfig) -> ImapClient:
        """Build an ImapClient from a MailAccountConfig.

        ImapClient takes legacy mailpilot AccountConfig + SyncConfig shapes
        (it reads via duck-typed attribute access). We construct equivalent
        SimpleNamespace objects rather than refactoring the client to take
        primitives — that refactor is deferred to SP3.
        """
        host, port = _PROVIDER_HOSTS.get(
            account.provider, ("imap.gmail.com", 993)
        )
        password = (
            self.secrets.resolve(account.credentials_ref)
            if account.credentials_ref
            else None
        )
        auth_method = "oauth2" if account.auth_method == "oauth" else "password"

        legacy_account = SimpleNamespace(
            email=account.identifier,
            name=account.identifier,
            provider=account.provider,
            imap=SimpleNamespace(
                host=host,
                port=port,
                encryption="tls",
                auth=SimpleNamespace(
                    method=auth_method,
                    password=password,
                ),
            ),
        )
        legacy_sync = SimpleNamespace(
            idle_timeout=self._cfg.idle_timeout_seconds,
            reconnect_base_delay=5,
            reconnect_max_delay=300,
        )
        return ImapClient(account=legacy_account, sync_config=legacy_sync)

    async def _resolve_account(self, account_id: int) -> MailAccountConfig:
        """Map account_id (DB row PK) → MailAccountConfig (config.yaml entry)."""
        async with self.storage.db.execute(
            "SELECT account_identifier FROM accounts WHERE id=?",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise LookupError(f"account_id={account_id} not in DB")
        identifier = str(row["account_identifier"])
        if identifier not in self._accounts:
            raise LookupError(
                f"account_id={account_id} (identifier={identifier!r}) is not "
                f"configured in plugins.mail.accounts in config.yaml"
            )
        return self._accounts[identifier]

    # ─── Lifecycle hooks ───────────────────────────────────────────────────

    async def setup(self) -> None:
        log.info("mail plugin setup: %d account(s) configured", len(self._accounts))

    async def backfill(
        self, account_id: int, *, since: datetime | None = None
    ) -> None:
        await self.sync_once(account_id)
        await self._mark_backfilled(account_id)

    async def sync_once(self, account_id: int) -> None:
        account = await self._resolve_account(account_id)
        imap = self._imap_factory(account)
        try:
            await imap.connect("INBOX")
            result = await sync_account_mailbox(
                storage=self.storage,
                imap=imap,
                account_id=account_id,
                mailbox="INBOX",
                gmail_thread_resolver=None,
                labels=[],
            )
            log.info(
                "sync_once account=%d mailbox=INBOX inserted=%d skipped=%d",
                account_id,
                result.inserted,
                result.skipped,
            )
        finally:
            await imap.disconnect("INBOX")

    async def daemon(self, account_id: int) -> None:
        """Polling-style daemon: sync_once every idle_timeout. SP2 swaps to IDLE."""
        await self._resolve_account(account_id)
        log.info("mail daemon starting for account=%d", account_id)
        while True:
            try:
                await self.sync_once(account_id)
            except Exception:  # noqa: BLE001
                log.exception(
                    "daemon sync_once failed; retrying in %ds",
                    self._cfg.idle_timeout_seconds,
                )
            await asyncio.sleep(self._cfg.idle_timeout_seconds)

    async def teardown(self) -> None:
        log.info("mail plugin teardown")

    # ─── Internals ─────────────────────────────────────────────────────────

    async def _mark_backfilled(self, account_id: int) -> None:
        """Update accounts.backfilled_at after a successful backfill.

        Plugins reach into self.storage.db here because SP0 didn't expose a
        Storage helper for this. SP3 should add `Storage.mark_backfilled()`.
        """
        await self.storage.db.execute(
            "UPDATE accounts SET backfilled_at=? WHERE id=?",
            (datetime.now(UTC).isoformat(), account_id),
        )
        await self.storage.db.commit()
