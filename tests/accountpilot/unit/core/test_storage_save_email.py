from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from accountpilot.core.cas import CASStore
from accountpilot.core.models import AttachmentBlob, EmailMessage
from accountpilot.core.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite


async def _seed_owner_and_account(db: aiosqlite.Connection) -> tuple[int, int]:
    now = datetime.now(UTC).isoformat()
    cur = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES ('Aren', 'E', 1, ?, ?)",
        (now, now),
    )
    owner_id = cur.lastrowid
    cur = await db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'gmail', 'a@b.com', 1, ?, ?)",
        (owner_id, now, now),
    )
    account_id = cur.lastrowid
    await db.commit()
    return owner_id, account_id


def _make_email(account_id: int, **overrides) -> EmailMessage:
    base = dict(
        account_id=account_id,
        external_id="<msg-1@x>",
        sent_at=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        received_at=datetime(2026, 5, 1, 10, 0, 5, tzinfo=UTC),
        direction="inbound",
        from_address="Foo Bar <foo@bar.com>",
        to_addresses=["aren@a.com"],
        cc_addresses=[],
        bcc_addresses=[],
        subject="Hello",
        body_text="Body text body text",
        body_html=None,
        in_reply_to=None,
        references=[],
        imap_uid=42,
        mailbox="INBOX",
        gmail_thread_id=None,
        labels=["INBOX"],
        raw_headers={"Subject": "Hello"},
        attachments=[],
    )
    base.update(overrides)
    return EmailMessage(**base)


async def test_save_email_inserts_message_and_resolves_people(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    result = await storage.save_email(_make_email(account_id))
    assert result.action == "inserted"

    async with tmp_db.execute(
        "SELECT subject FROM email_details WHERE message_id=?", (result.message_id,)
    ) as cur:
        assert (await cur.fetchone())["subject"] == "Hello"

    async with tmp_db.execute(
        "SELECT p.name, mp.role FROM message_people mp "
        "JOIN people p ON p.id=mp.person_id "
        "WHERE mp.message_id=? ORDER BY mp.role",
        (result.message_id,),
    ) as cur:
        rows = [(r["name"], r["role"]) for r in await cur.fetchall()]
    assert ("Foo", "from") in rows
    assert any(role == "to" for _, role in rows)


async def test_save_email_dedup_returns_skipped(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_email(account_id)
    r1 = await storage.save_email(msg)
    r2 = await storage.save_email(msg)
    assert r1.action == "inserted"
    assert r2.action == "skipped"
    assert r2.message_id == r1.message_id

    async with tmp_db.execute("SELECT COUNT(*) FROM messages") as cur:
        assert (await cur.fetchone())[0] == 1


async def test_save_email_writes_attachments_to_cas_and_attachments_table(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_email(
        account_id,
        attachments=[
            AttachmentBlob(filename="hi.txt", content=b"hello", mime_type="text/plain")
        ],
    )
    result = await storage.save_email(msg)
    async with tmp_db.execute(
        "SELECT filename, content_hash, cas_path, size_bytes "
        "FROM attachments WHERE message_id=?",
        (result.message_id,),
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["filename"] == "hi.txt"
    assert row["size_bytes"] == 5
    assert (tmp_runtime / "attachments" / row["cas_path"]).read_bytes() == b"hello"


async def test_save_email_persists_email_details_json_columns(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_email(
        account_id,
        labels=["INBOX", "IMPORTANT"],
        references=["<a@x>", "<b@x>"],
        raw_headers={"Subject": "Hello", "From": "foo@bar"},
    )
    result = await storage.save_email(msg)
    async with tmp_db.execute(
        "SELECT labels_json, references_json, raw_headers_json "
        "FROM email_details WHERE message_id=?",
        (result.message_id,),
    ) as cur:
        row = await cur.fetchone()
    assert json.loads(row["labels_json"]) == ["INBOX", "IMPORTANT"]
    assert json.loads(row["references_json"]) == ["<a@x>", "<b@x>"]
    assert json.loads(row["raw_headers_json"]) == {
        "Subject": "Hello",
        "From": "foo@bar",
    }


async def test_save_email_fts_row_searchable(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    await storage.save_email(_make_email(account_id, body_text="lorem ipsum dolor"))
    async with tmp_db.execute(
        "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'lorem'"
    ) as cur:
        assert (await cur.fetchone()) is not None


async def test_save_email_uses_account_source_not_hardcoded(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    """messages.source must mirror accounts.source, not be hardcoded to 'gmail'."""
    # Seed an owner + an Outlook account (not Gmail).
    now = datetime.now(UTC).isoformat()
    cur = await tmp_db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES ('Aren', 'E', 1, ?, ?)",
        (now, now),
    )
    owner_id = cur.lastrowid
    cur = await tmp_db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'outlook', 'a@b.com', 1, ?, ?)",
        (owner_id, now, now),
    )
    account_id = cur.lastrowid
    await tmp_db.commit()

    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    result = await storage.save_email(_make_email(account_id))

    async with tmp_db.execute(
        "SELECT source FROM messages WHERE id=?", (result.message_id,)
    ) as cur:
        row = await cur.fetchone()
    assert row["source"] == "outlook"
