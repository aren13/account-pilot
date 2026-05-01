from __future__ import annotations

from pathlib import Path  # noqa: TC003 - used at runtime in test signatures

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage
from accountpilot.plugins.mail.config import MailAccountConfig, MailPluginConfig
from accountpilot.plugins.mail.plugin import MailPlugin
from tests.accountpilot.plugins.mail.conftest import FakeImapClient, make_rfc822


async def test_mail_plugin_sync_once_ingests(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        owner = await storage.upsert_owner(
            name="Aren",
            surname=None,
            identifiers=[Identifier(kind="email", value="aren@example.com")],
        )
        account_id = await storage.upsert_account(
            source="gmail",
            identifier="aren@example.com",
            owner_id=owner,
        )

        cfg = MailPluginConfig(
            accounts=[
                MailAccountConfig(
                    identifier="aren@example.com",
                    owner="aren@example.com",
                    provider="gmail",
                    credentials_ref="literal-pw",
                )
            ],
        )
        fake = FakeImapClient({"INBOX": [(1, make_rfc822(1))]})

        plugin = MailPlugin(
            config=cfg.model_dump(),
            storage=storage,
            secrets=Secrets({}),
        )
        # Inject the fake at the connection-factory seam.
        plugin._imap_factory = lambda account: fake

        await plugin.setup()
        await plugin.sync_once(account_id)

        async with db.execute("SELECT COUNT(*) AS c FROM messages") as cur:
            assert (await cur.fetchone())["c"] == 1


async def test_mail_plugin_backfill_calls_sync_once(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        owner = await storage.upsert_owner(
            name="Aren",
            surname=None,
            identifiers=[Identifier(kind="email", value="aren@example.com")],
        )
        account_id = await storage.upsert_account(
            source="gmail",
            identifier="aren@example.com",
            owner_id=owner,
        )

        cfg = MailPluginConfig(
            accounts=[
                MailAccountConfig(
                    identifier="aren@example.com",
                    owner="aren@example.com",
                    provider="gmail",
                    credentials_ref="literal-pw",
                )
            ]
        )
        fake = FakeImapClient({"INBOX": [(i, make_rfc822(i)) for i in range(1, 6)]})
        plugin = MailPlugin(
            config=cfg.model_dump(), storage=storage, secrets=Secrets({})
        )
        plugin._imap_factory = lambda account: fake

        await plugin.setup()
        await plugin.backfill(account_id)

        async with db.execute("SELECT COUNT(*) AS c FROM messages") as cur:
            assert (await cur.fetchone())["c"] == 5
