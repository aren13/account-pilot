"""Tests for the MailPilot email composer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from mailpilot.models import SendRequest
from mailpilot.smtp.composer import EmailComposer, _quote_body


def _mock_original(
    subject: str = "Hello",
    from_address: str = "alice@example.com",
    from_name: str = "Alice",
    message_id: str = "<orig@example.com>",
    references_hdr: str | None = None,
    cc_addresses: str | None = None,
) -> dict:
    """Return a dict resembling a db.get_message() result."""
    return {
        "mp_id": "mp-000001",
        "message_id": message_id,
        "from_address": from_address,
        "from_name": from_name,
        "to_addresses": json.dumps(["bob@example.com"]),
        "cc_addresses": cc_addresses,
        "subject": subject,
        "date": "2026-01-15T10:00:00",
        "in_reply_to": None,
        "references_hdr": references_hdr,
        "account_id": 1,
        "folder": "INBOX",
        "uid": 42,
        "preview": "Original body text",
    }


def _make_composer(
    original: dict | None = None,
) -> tuple[
    EmailComposer,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
]:
    """Build a composer with fully mocked dependencies."""
    db = AsyncMock()
    if original is not None:
        db.get_message.return_value = original
    else:
        db.get_message.return_value = None

    smtp_client = AsyncMock()
    smtp_client.send.return_value = "<sent@example.com>"

    imap_client = AsyncMock()
    event_emitter = AsyncMock()

    account = MagicMock()
    account.name = "test"
    account.email = "bob@example.com"
    account.display_name = "Bob"

    composer = EmailComposer(
        db=db,
        smtp_client=smtp_client,
        imap_client=imap_client,
        event_emitter=event_emitter,
        account=account,
    )
    return composer, db, smtp_client, imap_client, event_emitter


class TestComposeNewMessage:
    """Test composing and sending new messages."""

    @pytest.mark.asyncio
    async def test_compose_new_message(self) -> None:
        """compose_and_send sets all required headers."""
        composer, _, smtp, imap, _ = _make_composer()

        request = SendRequest(
            account="test",
            to=["alice@example.com"],
            cc=["carol@example.com"],
            subject="Test Subject",
            body="Hello, world!",
        )

        result = await composer.compose_and_send(request)

        assert result == "<sent@example.com>"
        smtp.send.assert_awaited_once()

        # Inspect the message passed to send()
        sent_msg = smtp.send.call_args[0][0]
        assert sent_msg["To"] == "alice@example.com"
        assert sent_msg["Cc"] == "carol@example.com"
        assert sent_msg["Subject"] == "Test Subject"
        assert "Bob <bob@example.com>" in sent_msg["From"]
        assert sent_msg["Message-ID"] is not None
        assert sent_msg["Date"] is not None

    @pytest.mark.asyncio
    async def test_compose_with_html(self) -> None:
        """Multipart message has both plain text and HTML."""
        composer, _, smtp, _, _ = _make_composer()

        request = SendRequest(
            account="test",
            to=["alice@example.com"],
            subject="HTML Test",
            body="Plain text",
            html="<p>Rich text</p>",
        )

        await composer.compose_and_send(request)

        sent_msg = smtp.send.call_args[0][0]
        # Should be multipart with alternatives
        body = sent_msg.get_body(preferencelist=("plain",))
        assert body is not None
        html = sent_msg.get_body(preferencelist=("html",))
        assert html is not None


class TestReply:
    """Test reply composition."""

    @pytest.mark.asyncio
    async def test_reply_sets_headers(self) -> None:
        """Reply sets In-Reply-To, References, and Re: prefix."""
        original = _mock_original(
            references_hdr="<ref1@example.com>"
        )
        composer, _, smtp, imap, _ = _make_composer(original)

        await composer.reply("mp-000001", "My reply")

        sent_msg = smtp.send.call_args[0][0]
        assert sent_msg["In-Reply-To"] == "<orig@example.com>"
        assert "<ref1@example.com>" in sent_msg["References"]
        assert "<orig@example.com>" in sent_msg["References"]
        assert sent_msg["Subject"] == "Re: Hello"

    @pytest.mark.asyncio
    async def test_reply_quotes_body(self) -> None:
        """Reply body contains quoted original text."""
        original = _mock_original()
        composer, _, smtp, _, _ = _make_composer(original)

        await composer.reply("mp-000001", "My reply")

        sent_msg = smtp.send.call_args[0][0]
        body = sent_msg.get_body(preferencelist=("plain",))
        content = body.get_content()
        assert "> Original body text" in content
        assert "My reply" in content

    @pytest.mark.asyncio
    async def test_reply_no_double_re_prefix(self) -> None:
        """Re: prefix is not duplicated on already-prefixed subject."""
        original = _mock_original(subject="Re: Hello")
        composer, _, smtp, _, _ = _make_composer(original)

        await composer.reply("mp-000001", "reply")

        sent_msg = smtp.send.call_args[0][0]
        assert sent_msg["Subject"] == "Re: Hello"
        assert not sent_msg["Subject"].startswith("Re: Re:")

    @pytest.mark.asyncio
    async def test_reply_sets_answered_flag(self) -> None:
        """\\Answered flag is set on the original message."""
        original = _mock_original()
        composer, _, _, imap, _ = _make_composer(original)

        await composer.reply("mp-000001", "reply")

        imap.set_flags.assert_awaited_once_with(
            "INBOX", [42], ["\\Answered"]
        )


class TestForward:
    """Test forward composition."""

    @pytest.mark.asyncio
    async def test_forward_includes_original(self) -> None:
        """Forwarded message contains the forward header block."""
        original = _mock_original()
        composer, _, smtp, _, _ = _make_composer(original)

        await composer.forward(
            "mp-000001", ["carol@example.com"]
        )

        sent_msg = smtp.send.call_args[0][0]
        body = sent_msg.get_body(preferencelist=("plain",))
        content = body.get_content()
        assert "Forwarded message" in content
        assert "From: alice@example.com" in content
        assert "Subject: Hello" in content
        assert "Original body text" in content

    @pytest.mark.asyncio
    async def test_forward_no_double_fwd_prefix(self) -> None:
        """Fwd: prefix is not duplicated."""
        original = _mock_original(subject="Fwd: Hello")
        composer, _, smtp, _, _ = _make_composer(original)

        await composer.forward(
            "mp-000001", ["carol@example.com"]
        )

        sent_msg = smtp.send.call_args[0][0]
        assert sent_msg["Subject"] == "Fwd: Hello"
        assert not sent_msg["Subject"].startswith("Fwd: Fwd:")


class TestImapAndEvents:
    """Test IMAP saving and event emission."""

    @pytest.mark.asyncio
    async def test_sent_saved_to_imap(self) -> None:
        """Sent message is appended to the IMAP Sent folder."""
        composer, _, _, imap, _ = _make_composer()

        request = SendRequest(
            account="test",
            to=["alice@example.com"],
            subject="Test",
            body="Hello",
        )

        await composer.compose_and_send(request)

        imap.append_message.assert_awaited_once()
        call_args = imap.append_message.call_args
        assert call_args[0][0] == "Sent"
        assert call_args[1]["flags"] == ["\\Seen"]

    @pytest.mark.asyncio
    async def test_email_sent_event_emitted(self) -> None:
        """event_emitter.emit is called with email_sent."""
        composer, _, _, _, emitter = _make_composer()

        request = SendRequest(
            account="test",
            to=["alice@example.com"],
            subject="Test",
            body="Hello",
        )

        await composer.compose_and_send(request)

        emitter.emit.assert_awaited_once()
        call_args = emitter.emit.call_args
        assert call_args[0][0] == "email_sent"
        details = call_args[1]["details"]
        assert details["subject"] == "Test"
        assert details["to"] == ["alice@example.com"]


class TestHelpers:
    """Test helper functions."""

    def test_quote_body_helper(self) -> None:
        """_quote_body prefixes each line with '> '."""
        result = _quote_body("line1\nline2\nline3")
        assert result == "> line1\n> line2\n> line3"

    def test_compose_message_id_format(self) -> None:
        """Message-ID has angle brackets and domain."""
        composer, _, smtp, _, _ = _make_composer()

        request = SendRequest(
            account="test",
            to=["alice@example.com"],
            subject="ID Test",
            body="Hello",
        )

        msg = composer._build_message(request)
        mid = msg["Message-ID"]
        assert mid.startswith("<")
        assert mid.endswith(">")
        assert "@example.com>" in mid
