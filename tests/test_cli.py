"""Tests for the MailPilot Click CLI."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from mailpilot.cli import cli

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
    "subject": "Hello Bob",
    "date": "2025-06-15T10:00:00",
    "preview": "Hey Bob, how are you?",
    "has_attachments": False,
    "attachment_info": None,
    "size_bytes": 1234,
    "flags": ["\\Seen"],
    "maildir_path": None,
    "is_deleted": False,
    "tags": ["inbox", "unread"],
}


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture
def runner() -> CliRunner:
    """Return a Click CLI test runner."""
    return CliRunner()


def _make_mock_mp() -> MagicMock:
    """Build a fully mocked MailPilot instance."""
    mp = AsyncMock()
    mp.config = MagicMock()
    mp.config.accounts = []

    # Read operations
    mp.search = AsyncMock(
        return_value=[dict(_SAMPLE_MSG)]
    )
    mp.show = AsyncMock(return_value=dict(_SAMPLE_MSG))
    mp.show_thread = AsyncMock(
        return_value=[dict(_SAMPLE_MSG)]
    )
    mp.list_unread = AsyncMock(
        return_value=[dict(_SAMPLE_MSG)]
    )
    mp.count = AsyncMock(return_value=42)
    mp.events = AsyncMock(
        return_value=[
            {
                "id": 1,
                "event_type": "email_read",
                "created_at": "2025-06-15T10:00:00",
            }
        ]
    )

    # Write operations
    mp.send = AsyncMock(
        return_value="<sent-1@example.com>"
    )
    mp.reply = AsyncMock(
        return_value="<reply-1@example.com>"
    )
    mp.forward = AsyncMock(
        return_value="<fwd-1@example.com>"
    )

    # Management operations
    mp.mark_read = AsyncMock()
    mp.mark_unread = AsyncMock()
    mp.flag = AsyncMock()
    mp.unflag = AsyncMock()
    mp.move = AsyncMock()
    mp.delete = AsyncMock()
    mp.tag = AsyncMock()

    # Database
    mp.db = AsyncMock()
    mp.db.list_accounts = AsyncMock(
        return_value=[
            {"name": "test", "email": "test@example.com"}
        ]
    )

    # Tag manager
    mp._tag_manager = AsyncMock()
    mp._tag_manager.list_tags = AsyncMock(
        return_value=[
            {"name": "inbox", "message_count": 10},
            {"name": "unread", "message_count": 3},
        ]
    )

    # IMAP clients
    mp._imap_clients = {}

    # Context manager support
    mp.__aenter__ = AsyncMock(return_value=mp)
    mp.__aexit__ = AsyncMock(return_value=None)

    return mp


def _patch_mailpilot(mock_mp: MagicMock):
    """Patch get_mailpilot to return our mock."""
    return patch(
        "mailpilot.cli.get_mailpilot",
        return_value=mock_mp,
    )


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


class TestVersionFlag:
    def test_version_flag(self, runner: CliRunner) -> None:
        """--version shows the version string."""
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "mailpilot" in result.output
        assert "0.1.0" in result.output


class TestHelpShowsCommands:
    def test_help_shows_commands(
        self, runner: CliRunner
    ) -> None:
        """--help lists all top-level commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        expected = [
            "start",
            "stop",
            "status",
            "sync",
            "reindex",
            "search",
            "show",
            "thread",
            "unread",
            "count",
            "send",
            "reply",
            "forward",
            "read",
            "unread-mark",
            "flag",
            "unflag",
            "move",
            "delete",
            "account",
            "tag",
            "attachment",
            "events",
        ]
        for cmd in expected:
            assert cmd in result.output, (
                f"{cmd!r} not in help output"
            )


class TestSearchJsonOutput:
    def test_search_json_output(
        self, runner: CliRunner
    ) -> None:
        """search with mocked results returns JSON."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli, ["search", "from:alice"]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["mp_id"] == "mp-000001"


class TestSearchTableOutput:
    def test_search_table_output(
        self, runner: CliRunner
    ) -> None:
        """search -o table formats as columns."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli,
                ["-o", "table", "search", "from:alice"],
            )
        assert result.exit_code == 0
        assert "mp_id" in result.output
        assert "mp-000001" in result.output
        assert "alice@example.com" in result.output


class TestShowMessage:
    def test_show_message(
        self, runner: CliRunner
    ) -> None:
        """show mp-000001 returns message JSON."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli, ["show", "mp-000001"]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["mp_id"] == "mp-000001"
        assert data["subject"] == "Hello Bob"
        mock_mp.show.assert_awaited_once_with(
            "mp-000001"
        )


class TestUnreadCommand:
    def test_unread_command(
        self, runner: CliRunner
    ) -> None:
        """unread returns list of unread messages."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(cli, ["unread"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        mock_mp.list_unread.assert_awaited_once()


class TestCountCommand:
    def test_count_command(
        self, runner: CliRunner
    ) -> None:
        """count returns query and count."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli, ["count", "from:alice"]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["count"] == 42
        assert data["query"] == "from:alice"


class TestSendCommand:
    def test_send_command(
        self, runner: CliRunner
    ) -> None:
        """send verifies args are parsed correctly."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli,
                [
                    "send",
                    "--account",
                    "test",
                    "--to",
                    "bob@example.com",
                    "--subject",
                    "Hi",
                    "--body",
                    "Hello",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "sent"
        assert data["message_id"] == "<sent-1@example.com>"
        mock_mp.send.assert_awaited_once()
        call_kwargs = mock_mp.send.call_args
        assert call_kwargs.kwargs["account"] == "test"
        assert call_kwargs.kwargs["to"] == [
            "bob@example.com"
        ]
        assert call_kwargs.kwargs["subject"] == "Hi"


class TestReplyCommand:
    def test_reply_command(
        self, runner: CliRunner
    ) -> None:
        """reply with --all passes reply_all=True."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli,
                [
                    "reply",
                    "mp-000001",
                    "--body",
                    "Thanks!",
                    "--all",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "sent"
        mock_mp.reply.assert_awaited_once()
        call_kwargs = mock_mp.reply.call_args
        assert call_kwargs.kwargs["reply_all"] is True


class TestMarkReadCommand:
    def test_mark_read_command(
        self, runner: CliRunner
    ) -> None:
        """read marks multiple IDs as read."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli,
                ["read", "mp-000001", "mp-000002"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "ok"
        assert "mp-000001" in data["marked_read"]
        assert "mp-000002" in data["marked_read"]
        mock_mp.mark_read.assert_awaited_once_with(
            ["mp-000001", "mp-000002"]
        )


class TestDeletePermanentFlag:
    def test_delete_permanent_flag(
        self, runner: CliRunner
    ) -> None:
        """delete --permanent passes permanent=True."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli,
                [
                    "delete",
                    "mp-000001",
                    "--permanent",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["permanent"] is True
        mock_mp.delete.assert_awaited_once_with(
            ["mp-000001"], permanent=True
        )


class TestTagAddCommand:
    def test_tag_add_command(
        self, runner: CliRunner
    ) -> None:
        """tag add passes correct action and tags."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli,
                [
                    "tag",
                    "add",
                    "important",
                    "--id",
                    "mp-000001",
                ],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["action"] == "add"
        assert "important" in data["tags"]
        mock_mp.tag.assert_awaited_once()
        call_kwargs = mock_mp.tag.call_args.kwargs
        assert call_kwargs["action"] == "add"
        assert call_kwargs["tags"] == ["important"]
        assert call_kwargs["mp_ids"] == ["mp-000001"]


class TestAccountList:
    def test_account_list(
        self, runner: CliRunner
    ) -> None:
        """account list returns configured accounts."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli, ["account", "list"]
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == "test"


class TestEventsCommand:
    def test_events_command(
        self, runner: CliRunner
    ) -> None:
        """events returns list of events."""
        mock_mp = _make_mock_mp()
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli,
                ["events", "--type", "email_read"],
            )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["event_type"] == "email_read"
        mock_mp.events.assert_awaited_once()
        call_kwargs = mock_mp.events.call_args.kwargs
        assert call_kwargs["event_type"] == "email_read"


class TestErrorOutputJson:
    def test_error_output_json(
        self, runner: CliRunner
    ) -> None:
        """Errors produce JSON with exit code 1."""
        mock_mp = _make_mock_mp()
        mock_mp.search = AsyncMock(
            side_effect=RuntimeError("Connection failed")
        )
        with _patch_mailpilot(mock_mp):
            result = runner.invoke(
                cli, ["search", "broken"]
            )
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data
        assert "Connection failed" in data["error"]
