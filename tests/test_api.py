"""Tests for the MailPilot unified API class."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

if TYPE_CHECKING:
    from pathlib import Path

from mailpilot import MailPilot

# ------------------------------------------------------------------
# Sample data
# ------------------------------------------------------------------

_SAMPLE_MSG = {
    "id": 1,
    "mp_id": "mp-000001",
    "account_id": 1,
    "message_id": "<msg-1@example.com>",
    "uid": 101,
    "folder": "INBOX",
    "thread_id": "t-abc123",
    "from_address": "alice@example.com",
    "from_name": "Alice",
    "to_addresses": json.dumps(["bob@example.com"]),
    "cc_addresses": None,
    "bcc_addresses": None,
    "subject": "Hello Bob",
    "date": "2025-06-15T10:00:00",
    "in_reply_to": None,
    "references_hdr": None,
    "preview": "Hey Bob, how are you?",
    "has_attachments": False,
    "attachment_info": None,
    "size_bytes": 1234,
    "flags": ["\\Seen"],
    "maildir_path": None,
    "xapian_docid": None,
    "is_deleted": False,
    "created_at": "2025-06-15T10:00:00",
    "updated_at": "2025-06-15T10:00:00",
}

_SAMPLE_MSG_2 = {
    **_SAMPLE_MSG,
    "id": 2,
    "mp_id": "mp-000002",
    "uid": 102,
    "date": "2025-06-15T11:00:00",
    "subject": "Re: Hello Bob",
    "from_address": "bob@example.com",
    "from_name": "Bob",
    "in_reply_to": "<msg-1@example.com>",
}


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest_asyncio.fixture
async def mailpilot(tmp_path: Path) -> MailPilot:
    """Create a MailPilot instance with all internals mocked."""
    config_yaml = tmp_path / "config.yaml"
    config_yaml.write_text(
        """\
mailpilot:
  data_dir: "{data_dir}"
accounts:
  - name: test
    email: test@example.com
    provider: custom
    imap:
      host: imap.example.com
      port: 993
      encryption: tls
      auth:
        method: password
        password_cmd: "echo secret"
    smtp:
      host: smtp.example.com
      port: 587
      encryption: starttls
      auth:
        method: password
        password_cmd: "echo secret"
""".format(data_dir=str(tmp_path / "data")),
        encoding="utf-8",
    )

    mp = MailPilot(config_path=config_yaml)

    # Mock database
    mock_db = AsyncMock()
    mock_db.get_message = AsyncMock(
        return_value=dict(_SAMPLE_MSG)
    )
    mock_db.get_messages_by_thread = AsyncMock(
        return_value=[
            dict(_SAMPLE_MSG),
            dict(_SAMPLE_MSG_2),
        ]
    )
    mock_db.search_messages = AsyncMock(
        return_value=[dict(_SAMPLE_MSG)]
    )
    mock_db.get_message_tags = AsyncMock(
        return_value=["inbox", "unread"]
    )
    mock_db.get_account = AsyncMock(
        return_value={"id": 1, "name": "test"}
    )
    mock_db.get_account_by_id = AsyncMock(
        return_value={"id": 1, "name": "test"}
    )
    mock_db.update_message = AsyncMock()
    mock_db.delete_message = AsyncMock()
    mock_db.insert_event = AsyncMock(return_value=1)
    mock_db.conn = MagicMock()

    # count_unread query mock
    mock_cursor = AsyncMock()
    mock_cursor.fetchone = AsyncMock(return_value=(5,))
    mock_db.conn.execute = AsyncMock(
        return_value=mock_cursor
    )

    mp._db = mock_db

    # Mock search query (xapian)
    mock_sq = MagicMock()
    mock_sq.async_search = AsyncMock(
        return_value=[
            {"mp_id": "mp-000001", "relevance": 1.0},
        ]
    )
    mock_sq.async_count = AsyncMock(return_value=42)
    mock_sq.close = MagicMock()
    mp._search_query = mock_sq

    # Mock tag manager
    mock_tm = AsyncMock()
    mock_tm.add_tags = AsyncMock()
    mock_tm.remove_tags = AsyncMock()
    mock_tm.get_tags = AsyncMock(
        return_value=["inbox", "unread"]
    )
    mp._tag_manager = mock_tm

    # Mock event emitter
    mock_ee = AsyncMock()
    mock_ee.emit = AsyncMock()
    mock_ee.get_events = AsyncMock(
        return_value=[
            {
                "id": 1,
                "event_type": "email_read",
                "created_at": "2025-06-15T10:00:00",
            }
        ]
    )
    mp._event_emitter = mock_ee

    # Mock IMAP client
    mock_imap = AsyncMock()
    mock_imap.set_flags = AsyncMock()
    mock_imap.remove_flags = AsyncMock()
    mock_imap.move_messages = AsyncMock()
    mock_imap.delete_messages = AsyncMock()
    mock_imap.disconnect = AsyncMock()
    mp._imap_clients["test"] = mock_imap

    # Mock SMTP client
    mock_smtp = AsyncMock()
    mock_smtp.send = AsyncMock(
        return_value="<sent-1@example.com>"
    )
    mock_smtp.close = AsyncMock()
    mp._smtp_clients["test"] = mock_smtp

    return mp


# ------------------------------------------------------------------
# Read operation tests
# ------------------------------------------------------------------


class TestSearch:
    @pytest.mark.asyncio
    async def test_search_returns_results(
        self, mailpilot: MailPilot
    ) -> None:
        """Search via xapian returns messages with tags."""
        results = await mailpilot.search("hello")
        assert len(results) == 1
        assert results[0]["mp_id"] == "mp-000001"
        assert results[0]["tags"] == ["inbox", "unread"]
        mailpilot._search_query.async_search.assert_awaited_once()  # type: ignore[union-attr]


class TestShow:
    @pytest.mark.asyncio
    async def test_show_returns_message(
        self, mailpilot: MailPilot
    ) -> None:
        """show() returns a message dict with tags."""
        msg = await mailpilot.show("mp-000001")
        assert msg["mp_id"] == "mp-000001"
        assert msg["subject"] == "Hello Bob"
        assert "tags" in msg
        mailpilot.db.get_message.assert_awaited_with(
            "mp-000001"
        )


class TestShowThread:
    @pytest.mark.asyncio
    async def test_show_thread_returns_ordered(
        self, mailpilot: MailPilot
    ) -> None:
        """show_thread() returns all messages with tags."""
        msgs = await mailpilot.show_thread("t-abc123")
        assert len(msgs) == 2
        assert msgs[0]["mp_id"] == "mp-000001"
        assert msgs[1]["mp_id"] == "mp-000002"
        for m in msgs:
            assert "tags" in m


class TestListUnread:
    @pytest.mark.asyncio
    async def test_list_unread(
        self, mailpilot: MailPilot
    ) -> None:
        """list_unread() searches with tag:unread."""
        await mailpilot.list_unread()
        mailpilot._search_query.async_search.assert_awaited()  # type: ignore[union-attr]
        call_args = (
            mailpilot._search_query.async_search.call_args  # type: ignore[union-attr]
        )
        assert "tag:unread" in call_args[0][0]


class TestCount:
    @pytest.mark.asyncio
    async def test_count_query(
        self, mailpilot: MailPilot
    ) -> None:
        """count() delegates to xapian async_count."""
        result = await mailpilot.count("from:alice")
        assert result == 42
        mailpilot._search_query.async_count.assert_awaited_with(  # type: ignore[union-attr]
            "from:alice"
        )


class TestCountUnread:
    @pytest.mark.asyncio
    async def test_count_unread_per_account(
        self, mailpilot: MailPilot
    ) -> None:
        """count_unread() returns per-account counts + total."""
        result = await mailpilot.count_unread()
        assert "accounts" in result
        assert "total" in result
        assert result["accounts"]["test"] == 5
        assert result["total"] == 5


# ------------------------------------------------------------------
# Write operation tests
# ------------------------------------------------------------------


class TestSend:
    @pytest.mark.asyncio
    async def test_send_creates_message(
        self, mailpilot: MailPilot
    ) -> None:
        """send() calls SMTP and emits an event."""
        mid = await mailpilot.send(
            account="test",
            to=["bob@example.com"],
            subject="Test",
            body="Hello",
        )
        assert mid == "<sent-1@example.com>"
        mailpilot._smtp_clients["test"].send.assert_awaited_once()
        mailpilot._event_emitter.emit.assert_awaited()  # type: ignore[union-attr]


class TestReply:
    @pytest.mark.asyncio
    async def test_reply_sets_headers(
        self, mailpilot: MailPilot
    ) -> None:
        """reply() sends with Re: prefix and in_reply_to."""
        mid = await mailpilot.reply(
            "mp-000001", body="Thanks!"
        )
        assert mid == "<sent-1@example.com>"
        send_call = (
            mailpilot._smtp_clients["test"].send.call_args
        )
        # Subject should have Re: prefix (original already
        # has \\Seen, not Re:)
        assert "Re:" in send_call.kwargs.get(
            "subject", send_call[1].get("subject", "")
        )


class TestForward:
    @pytest.mark.asyncio
    async def test_forward_includes_original(
        self, mailpilot: MailPilot
    ) -> None:
        """forward() includes original body in forwarded text."""
        mid = await mailpilot.forward(
            "mp-000001",
            to=["charlie@example.com"],
            body="FYI",
        )
        assert mid == "<sent-1@example.com>"
        send_call = (
            mailpilot._smtp_clients["test"].send.call_args
        )
        body_arg = send_call.kwargs.get(
            "body", send_call[1].get("body", "")
        )
        assert "Forwarded" in body_arg
        assert "FYI" in body_arg


# ------------------------------------------------------------------
# Management operation tests
# ------------------------------------------------------------------


class TestMarkRead:
    @pytest.mark.asyncio
    async def test_mark_read_updates_all(
        self, mailpilot: MailPilot
    ) -> None:
        """mark_read updates IMAP flags, DB, tags, and emits."""
        await mailpilot.mark_read(["mp-000001"])

        imap = mailpilot._imap_clients["test"]
        imap.set_flags.assert_awaited_once_with(
            "INBOX", [101], ["\\Seen"]
        )
        mailpilot.db.update_message.assert_awaited()
        mailpilot._tag_manager.remove_tags.assert_awaited_with(  # type: ignore[union-attr]
            ["mp-000001"], ["unread"]
        )
        mailpilot._event_emitter.emit.assert_awaited()  # type: ignore[union-attr]


class TestMarkUnread:
    @pytest.mark.asyncio
    async def test_mark_unread_updates_all(
        self, mailpilot: MailPilot
    ) -> None:
        """mark_unread removes \\Seen, adds unread tag."""
        await mailpilot.mark_unread(["mp-000001"])

        imap = mailpilot._imap_clients["test"]
        imap.remove_flags.assert_awaited_once_with(
            "INBOX", [101], ["\\Seen"]
        )
        mailpilot._tag_manager.add_tags.assert_awaited_with(  # type: ignore[union-attr]
            ["mp-000001"], ["unread"]
        )


class TestFlag:
    @pytest.mark.asyncio
    async def test_flag_updates_all(
        self, mailpilot: MailPilot
    ) -> None:
        """flag() sets \\Flagged on IMAP and adds tag."""
        await mailpilot.flag(["mp-000001"])

        imap = mailpilot._imap_clients["test"]
        imap.set_flags.assert_awaited_once_with(
            "INBOX", [101], ["\\Flagged"]
        )
        mailpilot._tag_manager.add_tags.assert_awaited_with(  # type: ignore[union-attr]
            ["mp-000001"], ["flagged"]
        )
        mailpilot._event_emitter.emit.assert_awaited()  # type: ignore[union-attr]


class TestMove:
    @pytest.mark.asyncio
    async def test_move_updates_folder(
        self, mailpilot: MailPilot
    ) -> None:
        """move() calls IMAP move and updates DB folder."""
        await mailpilot.move(
            ["mp-000001"], to_folder="Archive"
        )

        imap = mailpilot._imap_clients["test"]
        imap.move_messages.assert_awaited_once_with(
            "INBOX", [101], "Archive"
        )
        mailpilot.db.update_message.assert_awaited_with(
            "mp-000001", folder="Archive"
        )
        mailpilot._event_emitter.emit.assert_awaited()  # type: ignore[union-attr]


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_soft(
        self, mailpilot: MailPilot
    ) -> None:
        """Soft delete moves to trash via IMAP."""
        await mailpilot.delete(["mp-000001"])

        imap = mailpilot._imap_clients["test"]
        imap.delete_messages.assert_awaited_once_with(
            "INBOX", [101], permanent=False
        )
        mailpilot.db.delete_message.assert_awaited_with(
            "mp-000001"
        )

    @pytest.mark.asyncio
    async def test_delete_permanent(
        self, mailpilot: MailPilot
    ) -> None:
        """Permanent delete expunges and marks is_deleted."""
        await mailpilot.delete(
            ["mp-000001"], permanent=True
        )

        imap = mailpilot._imap_clients["test"]
        imap.delete_messages.assert_awaited_once_with(
            "INBOX", [101], permanent=True
        )
        mailpilot.db.update_message.assert_awaited_with(
            "mp-000001", is_deleted=True
        )


# ------------------------------------------------------------------
# Tag operation tests
# ------------------------------------------------------------------


class TestTag:
    @pytest.mark.asyncio
    async def test_tag_add_by_ids(
        self, mailpilot: MailPilot
    ) -> None:
        """tag(action='add') with mp_ids calls add_tags."""
        await mailpilot.tag(
            action="add",
            tags=["important"],
            mp_ids=["mp-000001"],
        )
        mailpilot._tag_manager.add_tags.assert_awaited_with(  # type: ignore[union-attr]
            ["mp-000001"], ["important"]
        )

    @pytest.mark.asyncio
    async def test_tag_add_by_query(
        self, mailpilot: MailPilot
    ) -> None:
        """tag(action='add') with query resolves IDs first."""
        await mailpilot.tag(
            action="add",
            tags=["urgent"],
            query="from:alice",
        )
        # Search should have been called to resolve IDs
        mailpilot._search_query.async_search.assert_awaited()  # type: ignore[union-attr]
        mailpilot._tag_manager.add_tags.assert_awaited()  # type: ignore[union-attr]
