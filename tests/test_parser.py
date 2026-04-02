"""Tests for the MailPilot email parser."""

from __future__ import annotations

import base64
import json
from email.message import EmailMessage

from mailpilot.imap.parser import EmailParser


def _make_simple_email(
    *,
    from_addr: str = "sender@example.com",
    from_name: str = "Sender Name",
    to_addr: str = "recipient@example.com",
    subject: str = "Test Subject",
    body: str = "Hello, this is a test email.",
    date: str = "Thu, 01 Jan 2026 12:00:00 +0000",
) -> bytes:
    """Build a simple RFC822 email and return raw bytes."""
    msg = EmailMessage()
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = date
    msg["Message-ID"] = "<test-001@example.com>"
    msg.set_content(body)
    return msg.as_bytes()


class TestParseSimpleEmail:
    """Test parsing a basic single-part email."""

    def test_parse_simple_email(self) -> None:
        raw = _make_simple_email()
        parser = EmailParser()
        result = parser.parse_message(raw)

        assert result["from_address"] == "sender@example.com"
        assert result["from_name"] == "Sender Name"
        assert result["subject"] == "Test Subject"
        assert result["message_id"] == "<test-001@example.com>"
        assert result["has_attachments"] is False
        assert result["attachment_info"] is None
        assert result["size_bytes"] == len(raw)

        to_addrs = json.loads(result["to_addresses"])
        assert "recipient@example.com" in to_addrs

        # Date should be present as ISO string
        assert result["date"] is not None

        # Preview should contain the body text
        assert result["preview"] is not None
        assert "Hello, this is a test email." in result["preview"]


class TestParseMultipart:
    """Test parsing multipart/alternative with plain + HTML."""

    def test_parse_multipart(self) -> None:
        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Multipart Test"
        msg["Date"] = "Thu, 01 Jan 2026 12:00:00 +0000"
        msg["Message-ID"] = "<multi-001@example.com>"
        msg.set_content("Plain text body here.")
        msg.add_alternative(
            "<html><body><p>HTML body here.</p></body></html>",
            subtype="html",
        )

        raw = msg.as_bytes()
        parser = EmailParser()
        plain, html = parser.parse_body(raw)

        assert plain is not None
        assert "Plain text body here." in plain
        assert html is not None
        assert "<p>HTML body here.</p>" in html


class TestParseAttachment:
    """Test parsing an email with an attachment."""

    def test_parse_attachment(self) -> None:
        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Subject"] = "Attachment Test"
        msg["Date"] = "Thu, 01 Jan 2026 12:00:00 +0000"
        msg["Message-ID"] = "<attach-001@example.com>"
        msg.set_content("See attached file.")
        msg.add_attachment(
            b"file content here",
            maintype="text",
            subtype="plain",
            filename="test.txt",
        )

        raw = msg.as_bytes()
        parser = EmailParser()
        result = parser.parse_message(raw)

        assert result["has_attachments"] is True
        assert result["attachment_info"] is not None

        att_info = json.loads(result["attachment_info"])
        assert len(att_info) >= 1

        filenames = [a["filename"] for a in att_info]
        assert "test.txt" in filenames


class TestParseReferences:
    """Test the parse_references helper."""

    def test_parse_references(self) -> None:
        parser = EmailParser()
        header = "<abc@example.com> <def@example.com> <ghi@example.com>"
        result = parser.parse_references(header)

        assert result == [
            "<abc@example.com>",
            "<def@example.com>",
            "<ghi@example.com>",
        ]

    def test_parse_references_empty(self) -> None:
        parser = EmailParser()
        assert parser.parse_references(None) == []


class TestParseEncodedSubject:
    """Test parsing an email with RFC2047 encoded subject."""

    def test_parse_encoded_subject(self) -> None:
        # Encode "Helloo Woorld" in base64 UTF-8 (RFC2047)
        original_subject = "Helloo Woorld"
        encoded = base64.b64encode(
            original_subject.encode("utf-8")
        ).decode("ascii")
        rfc2047_subject = f"=?UTF-8?B?{encoded}?="

        msg = EmailMessage()
        msg["From"] = "sender@example.com"
        msg["To"] = "recipient@example.com"
        msg["Date"] = "Thu, 01 Jan 2026 12:00:00 +0000"
        msg["Message-ID"] = "<encoded-001@example.com>"
        msg.set_content("Body text.")

        # Replace the subject header with the raw RFC2047 value.
        # EmailMessage would auto-encode, so we set it raw.
        msg["Subject"] = rfc2047_subject

        raw = msg.as_bytes()
        parser = EmailParser()
        result = parser.parse_message(raw)

        assert result["subject"] is not None
        assert original_subject in result["subject"]


class TestParseMalformedEmail:
    """Test that garbage bytes do not crash the parser."""

    def test_parse_malformed_email(self) -> None:
        garbage = b"\x00\x01\x02\xff\xfe invalid email data \x80\x90"
        parser = EmailParser()
        result = parser.parse_message(garbage)

        # Should return a dict with defaults, not crash
        assert isinstance(result, dict)
        assert result["message_id"] is not None  # may be empty string
        assert result["size_bytes"] == len(garbage)
        assert result["has_attachments"] is False


class TestParseBodyPlainOnly:
    """Test parsing an email with only a plain text body."""

    def test_parse_body_plain_only(self) -> None:
        raw = _make_simple_email(body="Only plain text here, no HTML.")
        parser = EmailParser()
        plain, html = parser.parse_body(raw)

        assert plain is not None
        assert "Only plain text here, no HTML." in plain
        assert html is None
