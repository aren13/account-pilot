"""Tests for the MailPilot async SQLite database layer."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio

from mailpilot.database import Database

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    """Create an in-memory database, initialize it, yield, then close."""
    database = Database(Path(":memory:"))
    await database.initialize()
    yield database
    await database.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

EXPECTED_TABLES = {
    "accounts",
    "messages",
    "tags",
    "message_tags",
    "rule_log",
    "outbox",
    "events",
}


async def _insert_account(db: Database, name: str = "test") -> int:
    """Insert a test account and return its id."""
    return await db.insert_account(
        name=name, email=f"{name}@example.com", display_name="Test User"
    )


async def _insert_message(
    db: Database,
    account_id: int,
    uid: int = 1,
    folder: str = "INBOX",
    **overrides,
) -> int:
    """Insert a test message with sensible defaults. Returns the row id."""
    defaults = dict(
        account_id=account_id,
        message_id=f"<msg-{uid}@example.com>",
        uid=uid,
        folder=folder,
        from_address="sender@example.com",
        to_addresses='["recipient@example.com"]',
        subject=f"Test subject {uid}",
        date=datetime(2025, 1, 1, 12, 0, 0).isoformat(),
    )
    defaults.update(overrides)
    return await db.insert_message(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSchemaInitialization:
    """Tests for database schema creation and migrations."""

    @pytest.mark.asyncio
    async def test_initialize_creates_tables(self, db: Database) -> None:
        """After initialize(), all 7 expected tables must exist."""
        cursor = await db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}

        for expected in EXPECTED_TABLES:
            assert expected in table_names, f"Table '{expected}' missing"

    @pytest.mark.asyncio
    async def test_migrations_idempotent(self, db: Database) -> None:
        """Running initialize() a second time must not raise."""
        # db fixture already called initialize(); call it again.
        await db.initialize()

        # Verify tables still exist and are intact.
        cursor = await db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        rows = await cursor.fetchall()
        table_names = {row[0] for row in rows}

        for expected in EXPECTED_TABLES:
            assert expected in table_names


class TestAccountCRUD:
    """Tests for account insertion and retrieval."""

    @pytest.mark.asyncio
    async def test_insert_and_get_account(self, db: Database) -> None:
        """Insert an account, retrieve by name, verify all fields."""
        account_id = await db.insert_account(
            name="personal",
            email="me@example.com",
            display_name="My Name",
            provider="gmail",
        )

        assert isinstance(account_id, int)
        assert account_id > 0

        account = await db.get_account("personal")
        assert account is not None
        assert account["name"] == "personal"
        assert account["email"] == "me@example.com"
        assert account["display_name"] == "My Name"
        assert account["provider"] == "gmail"
        assert account["is_active"] == 1
        assert account["created_at"] is not None


class TestMessageCRUD:
    """Tests for message insertion, mp_id generation, and retrieval."""

    @pytest.mark.asyncio
    async def test_insert_and_get_message(self, db: Database) -> None:
        """Insert a message, verify mp_id format, and round-trip via get_message."""
        acct_id = await _insert_account(db)
        row_id = await _insert_message(db, acct_id, uid=1)

        assert isinstance(row_id, int)
        assert row_id > 0

        msg = await db.get_message("mp-000001")
        assert msg is not None
        assert msg["mp_id"] == "mp-000001"
        assert msg["account_id"] == acct_id
        assert msg["message_id"] == "<msg-1@example.com>"
        assert msg["uid"] == 1
        assert msg["folder"] == "INBOX"
        assert msg["from_address"] == "sender@example.com"
        assert msg["to_addresses"] == '["recipient@example.com"]'
        assert msg["is_deleted"] == 0

    @pytest.mark.asyncio
    async def test_mp_id_auto_increment(self, db: Database) -> None:
        """Three sequential inserts produce mp-000001, mp-000002, mp-000003."""
        acct_id = await _insert_account(db)

        for i in range(1, 4):
            await _insert_message(db, acct_id, uid=i)

        for _i, expected_mp_id in enumerate(
            ["mp-000001", "mp-000002", "mp-000003"], start=1
        ):
            msg = await db.get_message(expected_mp_id)
            assert msg is not None, f"Message {expected_mp_id} not found"
            assert msg["mp_id"] == expected_mp_id

    @pytest.mark.asyncio
    async def test_message_unique_constraint(self, db: Database) -> None:
        """Inserting a duplicate (account_id, uid, folder) raises IntegrityError."""
        acct_id = await _insert_account(db)
        await _insert_message(db, acct_id, uid=42, folder="INBOX")

        with pytest.raises(Exception) as exc_info:
            await _insert_message(
                db,
                acct_id,
                uid=42,
                folder="INBOX",
                message_id="<different@example.com>",
            )

        # aiosqlite wraps sqlite3.IntegrityError
        err_str = str(exc_info.value)
        err_type = type(exc_info.value).__name__
        assert "UNIQUE constraint" in err_str or "Integrity" in err_type


class TestTagsCRUD:
    """Tests for tag management and message-tag associations."""

    @pytest.mark.asyncio
    async def test_tags_crud(self, db: Database) -> None:
        """Full lifecycle: create tag, add to message, get, remove, verify empty."""
        acct_id = await _insert_account(db)
        msg_row_id = await _insert_message(db, acct_id, uid=1)

        # Create tag and attach to message
        await db.add_message_tags(msg_row_id, ["urgent", "work"])
        tags = await db.get_message_tags(msg_row_id)
        assert sorted(tags) == ["urgent", "work"]

        # Remove one tag
        await db.remove_message_tags(msg_row_id, ["urgent"])
        tags = await db.get_message_tags(msg_row_id)
        assert tags == ["work"]

        # Remove the last tag
        await db.remove_message_tags(msg_row_id, ["work"])
        tags = await db.get_message_tags(msg_row_id)
        assert tags == []

    @pytest.mark.asyncio
    async def test_get_or_create_tag(self, db: Database) -> None:
        """Calling get_or_create_tag twice with the same name returns the same id."""
        tag_id_1 = await db.get_or_create_tag("important")
        tag_id_2 = await db.get_or_create_tag("important")

        assert tag_id_1 == tag_id_2
        assert isinstance(tag_id_1, int)

        # A different name produces a different id
        tag_id_3 = await db.get_or_create_tag("other")
        assert tag_id_3 != tag_id_1


class TestEvents:
    """Tests for event logging and querying."""

    @pytest.mark.asyncio
    async def test_insert_and_get_events(self, db: Database) -> None:
        """Insert events, query by type and since filter."""
        acct_id = await _insert_account(db)

        evt1 = await db.insert_event(acct_id, "sync_started", details="full sync")
        evt2 = await db.insert_event(acct_id, "message_received", message_id=1)
        evt3 = await db.insert_event(acct_id, "sync_started", details="delta sync")

        assert isinstance(evt1, int)
        assert isinstance(evt2, int)
        assert isinstance(evt3, int)

        # Filter by event_type
        sync_events = await db.get_events(event_type="sync_started")
        assert len(sync_events) == 2
        for ev in sync_events:
            assert ev["event_type"] == "sync_started"

        msg_events = await db.get_events(event_type="message_received")
        assert len(msg_events) == 1
        assert msg_events[0]["event_type"] == "message_received"

        # Filter by since (grab all events with a far-past timestamp)
        all_events = await db.get_events(since=datetime(2000, 1, 1))
        assert len(all_events) == 3

        # Future timestamp should return nothing
        far_future = datetime(2099, 1, 1)
        empty_events = await db.get_events(since=far_future)
        assert len(empty_events) == 0


class TestOutboxLifecycle:
    """Tests for the outbox queue (pending -> sent transition)."""

    @pytest.mark.asyncio
    async def test_outbox_lifecycle(self, db: Database) -> None:
        """Insert pending outbox entry, update to sent, verify status transition."""
        acct_id = await _insert_account(db)

        outbox_id = await db.insert_outbox(
            account_id=acct_id,
            to_addresses='["dest@example.com"]',
            subject="Hello",
            body_plain="Hi there",
        )
        assert isinstance(outbox_id, int)

        # Should appear in pending list
        pending = await db.get_pending_outbox()
        assert len(pending) == 1
        assert pending[0]["id"] == outbox_id
        assert pending[0]["status"] == "pending"
        assert pending[0]["subject"] == "Hello"

        # Mark as sent
        sent_at = datetime(2025, 6, 15, 10, 0, 0).isoformat()
        await db.update_outbox(outbox_id, status="sent", sent_at=sent_at)

        # Pending list should now be empty
        pending = await db.get_pending_outbox()
        assert len(pending) == 0

        # Verify the row was updated, not removed
        cursor = await db.conn.execute(
            "SELECT * FROM outbox WHERE id = ?", (outbox_id,)
        )
        row = await cursor.fetchone()
        assert row is not None
        entry = dict(row)
        assert entry["status"] == "sent"
        assert entry["sent_at"] == sent_at


class TestSoftDelete:
    """Tests for soft-deletion of messages."""

    @pytest.mark.asyncio
    async def test_delete_message_soft(self, db: Database) -> None:
        """delete_message sets is_deleted=1 but does not remove the row."""
        acct_id = await _insert_account(db)
        await _insert_message(db, acct_id, uid=1)

        # Confirm it exists and is not deleted
        msg = await db.get_message("mp-000001")
        assert msg is not None
        assert msg["is_deleted"] == 0

        # Soft delete
        await db.delete_message("mp-000001")

        # Row still exists
        msg = await db.get_message("mp-000001")
        assert msg is not None
        assert msg["is_deleted"] == 1
        assert msg["updated_at"] is not None


class TestSearchMessages:
    """Tests for the search_messages filter method."""

    @pytest.mark.asyncio
    async def test_search_messages_filters(self, db: Database) -> None:
        """Filter by account_id, folder, and is_deleted."""
        acct1 = await _insert_account(db, name="acct1")
        acct2 = await _insert_account(db, name="acct2")

        # Insert messages across accounts and folders
        await _insert_message(db, acct1, uid=1, folder="INBOX")
        await _insert_message(db, acct1, uid=2, folder="Sent")
        await _insert_message(db, acct2, uid=3, folder="INBOX")

        # Soft-delete one message in acct1/INBOX
        await db.delete_message("mp-000001")

        # All non-deleted messages
        results = await db.search_messages()
        assert len(results) == 2  # mp-000002 and mp-000003

        # Filter by account
        results = await db.search_messages(account_id=acct1)
        assert len(results) == 1
        assert results[0]["folder"] == "Sent"

        # Filter by folder
        results = await db.search_messages(folder="INBOX")
        assert len(results) == 1
        assert results[0]["account_id"] == acct2

        # Include deleted messages
        results = await db.search_messages(is_deleted=True)
        assert len(results) == 1
        assert results[0]["mp_id"] == "mp-000001"

        # Filter by account + folder with no matches
        results = await db.search_messages(account_id=acct2, folder="Sent")
        assert len(results) == 0
