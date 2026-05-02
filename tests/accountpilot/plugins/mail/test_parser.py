from __future__ import annotations

from datetime import UTC, datetime

from accountpilot.plugins.mail.parser import (
    parse_rfc822_to_email_message,
)

_SAMPLE_RFC822 = b"""Message-ID: <abc-123@example.com>
Date: Fri, 01 May 2026 12:00:00 +0000
From: "Foo Bar" <foo@example.com>
To: aren@example.com
Cc: cc@example.com
Subject: Hello
References: <ref1@example.com> <ref2@example.com>
In-Reply-To: <ref2@example.com>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Body text here.
"""


def test_parse_minimum_email() -> None:
    msg = parse_rfc822_to_email_message(
        raw_bytes=_SAMPLE_RFC822,
        account_id=1,
        mailbox="INBOX",
        imap_uid=42,
        direction="inbound",
        gmail_thread_id=None,
        labels=[],
    )
    assert msg.account_id == 1
    assert msg.imap_uid == 42
    assert msg.mailbox == "INBOX"
    assert msg.direction == "inbound"
    assert msg.external_id == "<abc-123@example.com>"
    assert msg.from_address == '"Foo Bar" <foo@example.com>'
    assert msg.to_addresses == ["aren@example.com"]
    assert msg.cc_addresses == ["cc@example.com"]
    assert msg.subject == "Hello"
    assert msg.body_text.strip() == "Body text here."
    assert msg.in_reply_to == "<ref2@example.com>"
    assert msg.references == ["<ref1@example.com>", "<ref2@example.com>"]
    assert msg.sent_at == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    assert msg.attachments == []


def test_parse_email_with_attachment() -> None:
    raw = (
        b"Message-ID: <att-1@x>\n"
        b"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        b"From: a@b\n"
        b"To: c@d\n"
        b"Subject: Att\n"
        b"MIME-Version: 1.0\n"
        b'Content-Type: multipart/mixed; boundary="BOUND"\n'
        b"\n"
        b"--BOUND\n"
        b"Content-Type: text/plain\n"
        b"\n"
        b"text body\n"
        b"--BOUND\n"
        b"Content-Type: application/octet-stream\n"
        b'Content-Disposition: attachment; filename="hi.bin"\n'
        b"Content-Transfer-Encoding: base64\n"
        b"\n"
        b"aGVsbG8=\n"
        b"--BOUND--\n"
    )
    msg = parse_rfc822_to_email_message(
        raw_bytes=raw, account_id=1, mailbox="INBOX",
        imap_uid=43, direction="inbound",
        gmail_thread_id=None, labels=[],
    )
    assert len(msg.attachments) == 1
    a = msg.attachments[0]
    assert a.filename == "hi.bin"
    assert a.content == b"hello"
    assert a.mime_type == "application/octet-stream"


def test_parse_propagates_raw_headers() -> None:
    msg = parse_rfc822_to_email_message(
        raw_bytes=_SAMPLE_RFC822, account_id=1, mailbox="INBOX",
        imap_uid=42, direction="inbound",
        gmail_thread_id=None, labels=[],
    )
    assert msg.raw_headers["Subject"] == "Hello"
    assert "abc-123" in msg.raw_headers["Message-ID"]


def test_parse_decodes_rfc2047_subject() -> None:
    """Encoded-word subjects (`=?utf-8?B?…?=`) must decode to plain text.

    The legacy parser stored these verbatim, so 1100/2238 real Gmail
    messages had unreadable subjects after the AP-SP1 backfill.
    """
    raw = (
        b"Message-ID: <enc-1@x>\n"
        b"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        b"From: a@b\n"
        b"To: c@d\n"
        b"Subject: =?UTF-8?B?TWVyaGFiYSBkw7xueWE=?=\n"
        b"\n"
        b"body\n"
    )
    msg = parse_rfc822_to_email_message(
        raw_bytes=raw, account_id=1, mailbox="INBOX",
        imap_uid=1, direction="inbound",
        gmail_thread_id=None, labels=[],
    )
    assert msg.subject == "Merhaba dünya"


def test_parse_decodes_rfc2047_continuation_subject() -> None:
    """RFC 2047 allows splitting one logical subject across multiple
    encoded-words on continuation lines. They must concatenate without
    inserting whitespace."""
    raw = (
        b"Message-ID: <enc-2@x>\n"
        b"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        b"From: a@b\n"
        b"To: c@d\n"
        b"Subject: =?utf-8?B?S29zbW9zIFl1bmFuaXN0YW4gVml6ZSBIaXptZXRsZXJpIFJh?=\n"
        b" =?utf-8?B?bmRldnUgZGV0YXnEsW7EsXo=?=\n"
        b"\n"
        b"body\n"
    )
    msg = parse_rfc822_to_email_message(
        raw_bytes=raw, account_id=1, mailbox="INBOX",
        imap_uid=1, direction="inbound",
        gmail_thread_id=None, labels=[],
    )
    assert msg.subject == "Kosmos Yunanistan Vize Hizmetleri Randevu detayınız"


def test_parse_decodes_rfc2047_from_display_name() -> None:
    """Display name in From: may also be encoded."""
    raw = (
        b"Message-ID: <enc-3@x>\n"
        b"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        b"From: =?iso-8859-9?Q?Ak=FDll=FD_=D6neri_Sistemi?= <ai@x.com>\n"
        b"To: c@d\n"
        b"Subject: hi\n"
        b"\n"
        b"body\n"
    )
    msg = parse_rfc822_to_email_message(
        raw_bytes=raw, account_id=1, mailbox="INBOX",
        imap_uid=1, direction="inbound",
        gmail_thread_id=None, labels=[],
    )
    assert "Akıllı Öneri Sistemi" in msg.from_address
