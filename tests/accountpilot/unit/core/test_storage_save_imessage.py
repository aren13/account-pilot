from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from accountpilot.core.cas import CASStore
from accountpilot.core.models import AttachmentBlob, IMessageMessage
from accountpilot.core.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite


def _now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


async def _seed_imessage_account(db: aiosqlite.Connection) -> int:
    cur = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES ('Aren', 'E', 1, ?, ?)",
        (_now_iso(), _now_iso()),
    )
    owner_id = cur.lastrowid
    cur = await db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'imessage', '+15551234567', 1, ?, ?)",
        (owner_id, _now_iso(), _now_iso()),
    )
    await db.commit()
    aid = cur.lastrowid
    assert aid is not None
    return aid


def _make_imessage(account_id: int, **overrides) -> IMessageMessage:
    base = dict(
        account_id=account_id,
        external_id="GUID-1",
        sent_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        direction="inbound",
        sender_handle="+1 (555) 987-6543",
        chat_guid="chat-1",
        participants=["+15551234567", "+15559876543"],
        body_text="hi from imessage",
        service="iMessage",
        is_read=True,
        date_read=None,
        attachments=[],
    )
    base.update(overrides)
    return IMessageMessage(**base)


async def test_save_imessage_inserts_message_and_details(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    result = await storage.save_imessage(_make_imessage(account_id))
    assert result.action == "inserted"

    async with tmp_db.execute(
        "SELECT chat_guid, service FROM imessage_details WHERE message_id=?",
        (result.message_id,),
    ) as cur:
        row = await cur.fetchone()
    assert row["chat_guid"] == "chat-1"
    assert row["service"] == "iMessage"


async def test_save_imessage_resolves_sender_and_participants(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    result = await storage.save_imessage(_make_imessage(account_id))
    async with tmp_db.execute(
        "SELECT role FROM message_people WHERE message_id=? ORDER BY role",
        (result.message_id,),
    ) as cur:
        rows = [r["role"] for r in await cur.fetchall()]
    assert "from" in rows
    assert "participant" in rows


async def test_save_imessage_dedup(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_imessage(account_id)
    r1 = await storage.save_imessage(msg)
    r2 = await storage.save_imessage(msg)
    assert r1.action == "inserted"
    assert r2.action == "skipped"


async def test_save_imessage_attachment(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_imessage(
        account_id,
        attachments=[
            AttachmentBlob(
                filename="pic.jpg", content=b"\xff\xd8\xff", mime_type="image/jpeg"
            )
        ],
    )
    result = await storage.save_imessage(msg)
    async with tmp_db.execute(
        "SELECT cas_path FROM attachments WHERE message_id=?", (result.message_id,)
    ) as cur:
        row = await cur.fetchone()
    cas_path = tmp_runtime / "attachments" / row["cas_path"]
    assert cas_path.read_bytes() == b"\xff\xd8\xff"
