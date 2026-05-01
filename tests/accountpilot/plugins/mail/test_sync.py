from __future__ import annotations

from typing import TYPE_CHECKING

from accountpilot.core.cas import CASStore

if TYPE_CHECKING:
    from pathlib import Path
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage
from accountpilot.plugins.mail.sync import sync_account_mailbox
from tests.accountpilot.plugins.mail.conftest import FakeImapClient, make_rfc822


async def _seed_account(storage: Storage) -> int:
    owner = await storage.upsert_owner(
        name="Aren", surname=None,
        identifiers=[Identifier(kind="email", value="aren@example.com")],
    )
    return await storage.upsert_account(
        source="gmail", identifier="aren@example.com", owner_id=owner,
    )


async def test_sync_inserts_new_messages(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        account_id = await _seed_account(storage)
        imap = FakeImapClient({
            "INBOX": [(1, make_rfc822(1)), (2, make_rfc822(2))],
        })

        result = await sync_account_mailbox(
            storage=storage, imap=imap,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )
        assert result.inserted == 2
        assert result.skipped == 0

        # Re-running picks up nothing new (dedup via watermark).
        result2 = await sync_account_mailbox(
            storage=storage, imap=imap,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )
        assert result2.inserted == 0
        assert result2.skipped == 0


async def test_sync_resumes_from_watermark(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        account_id = await _seed_account(storage)

        imap = FakeImapClient({"INBOX": [(1, make_rfc822(1)), (2, make_rfc822(2))]})
        await sync_account_mailbox(
            storage=storage, imap=imap,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )

        imap2 = FakeImapClient({"INBOX": [
            (1, make_rfc822(1)), (2, make_rfc822(2)),
            (3, make_rfc822(3)), (4, make_rfc822(4)),
        ]})
        result = await sync_account_mailbox(
            storage=storage, imap=imap2,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )
        assert result.inserted == 2

        async with db.execute("SELECT COUNT(*) AS c FROM messages") as cur:
            assert (await cur.fetchone())["c"] == 4
