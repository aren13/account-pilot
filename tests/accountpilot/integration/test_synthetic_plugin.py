from __future__ import annotations

from typing import TYPE_CHECKING

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage
from tests.accountpilot.fixtures.synthetic_plugin.plugin import SyntheticPlugin

if TYPE_CHECKING:
    from pathlib import Path


async def test_synthetic_plugin_end_to_end(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        owner = await storage.upsert_owner(
            name="Aren", surname="E",
            identifiers=[
                Identifier(kind="email", value="aren@x.com"),
                Identifier(kind="phone", value="+15551234567"),
            ],
        )
        mail_account = await storage.upsert_account(
            source="gmail", identifier="aren@x.com", owner_id=owner,
        )
        im_account = await storage.upsert_account(
            source="imessage", identifier="+15551234567", owner_id=owner,
        )
        plugin = SyntheticPlugin(
            config={}, storage=storage, secrets=Secrets({}),
            mail_account_id=mail_account, imessage_account_id=im_account,
        )
        await plugin.sync_once(mail_account)
        await plugin.sync_once(im_account)

        # Both message types present.
        async with db.execute(
            "SELECT source, COUNT(*) AS c FROM messages GROUP BY source"
        ) as cur:
            counts = {r["source"]: r["c"] for r in await cur.fetchall()}
        assert counts == {"gmail": 1, "imessage": 1}

        # Attachment is on disk + indexed.
        async with db.execute("SELECT cas_path FROM attachments") as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
        assert (tmp_runtime / "attachments" / rows[0]["cas_path"]).exists()

        # FTS finds the synthetic body text.
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'synthetic'"
        ) as cur:
            assert (await cur.fetchone()) is not None
