from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from accountpilot.core.cas import CASStore
from accountpilot.core.models import EmailMessage, Identifier
from accountpilot.core.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite


async def test_upsert_owner_creates_then_returns_existing(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    pid1 = await storage.upsert_owner(
        name="Aren", surname="E",
        identifiers=[
            Identifier(kind="email", value="aren@x.com"),
            Identifier(kind="phone", value="+905052490139"),
        ],
    )
    pid2 = await storage.upsert_owner(
        name="Aren", surname="E",
        identifiers=[Identifier(kind="email", value="aren@x.com")],
    )
    assert pid1 == pid2

    async with tmp_db.execute(
        "SELECT is_owner FROM people WHERE id=?", (pid1,)
    ) as cur:
        assert (await cur.fetchone())["is_owner"] == 1  # type: ignore[index]


async def test_upsert_account_idempotent(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    owner_id = await storage.upsert_owner(
        name="Aren", surname=None,
        identifiers=[Identifier(kind="email", value="a@b.com")],
    )
    a1 = await storage.upsert_account(
        source="gmail", identifier="a@b.com", owner_id=owner_id,
        credentials_ref="op://x/y/z",
    )
    a2 = await storage.upsert_account(
        source="gmail", identifier="a@b.com", owner_id=owner_id,
        credentials_ref="op://x/y/z",
    )
    assert a1 == a2


async def test_latest_external_id_and_sent_at(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    owner_id = await storage.upsert_owner(
        name="A", surname=None,
        identifiers=[Identifier(kind="email", value="a@b.com")],
    )
    account_id = await storage.upsert_account(
        source="gmail", identifier="a@b.com", owner_id=owner_id,
    )
    assert await storage.latest_external_id(account_id) is None
    assert await storage.latest_sent_at(account_id) is None

    def _email(ext_id: str, sent: datetime) -> EmailMessage:
        return EmailMessage(
            account_id=account_id, external_id=ext_id, sent_at=sent,
            received_at=None, direction="inbound", from_address="z@z",
            to_addresses=[], cc_addresses=[], bcc_addresses=[],
            subject="", body_text="", body_html=None, in_reply_to=None,
            references=[], imap_uid=0, mailbox="INBOX",
            gmail_thread_id=None, labels=[], raw_headers={}, attachments=[],
        )

    await storage.save_email(_email("a", datetime(2026, 5, 1, tzinfo=UTC)))
    await storage.save_email(_email("b", datetime(2026, 5, 2, tzinfo=UTC)))
    assert await storage.latest_external_id(account_id) == "b"
    assert await storage.latest_sent_at(account_id) == datetime(2026, 5, 2, tzinfo=UTC)
