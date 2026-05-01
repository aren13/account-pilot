from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from accountpilot.core.models import (
    AttachmentBlob,
    EmailMessage,
    Identifier,
    IMessageMessage,
    SaveResult,
)


def test_attachment_blob_requires_filename_and_content() -> None:
    blob = AttachmentBlob(filename="hello.txt", content=b"hi", mime_type="text/plain")
    assert blob.filename == "hello.txt"
    assert blob.content == b"hi"


def test_email_message_minimum_fields() -> None:
    msg = EmailMessage(
        account_id=1,
        external_id="<a@b>",
        sent_at=datetime(2026, 5, 1, 12, 0, 0),
        received_at=None,
        direction="inbound",
        from_address="a@b.com",
        to_addresses=["c@d.com"],
        cc_addresses=[],
        bcc_addresses=[],
        subject="hi",
        body_text="hello",
        body_html=None,
        in_reply_to=None,
        references=[],
        imap_uid=42,
        mailbox="INBOX",
        gmail_thread_id=None,
        labels=[],
        raw_headers={},
        attachments=[],
    )
    assert msg.from_address == "a@b.com"


def test_email_message_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError):
        EmailMessage(
            account_id=1, external_id="x", sent_at=datetime.now(),
            received_at=None, direction="sideways",  # type: ignore[arg-type]
            from_address="a@b", to_addresses=[], cc_addresses=[],
            bcc_addresses=[], subject="", body_text="", body_html=None,
            in_reply_to=None, references=[], imap_uid=0, mailbox="",
            gmail_thread_id=None, labels=[], raw_headers={}, attachments=[],
        )


def test_imessage_message_minimum_fields() -> None:
    msg = IMessageMessage(
        account_id=1,
        external_id="GUID",
        sent_at=datetime(2026, 5, 1),
        direction="outbound",
        sender_handle="+15551234567",
        chat_guid="chat-1",
        participants=["+15551234567", "+15559876543"],
        body_text="hi",
        service="iMessage",
        is_read=True,
        date_read=None,
        attachments=[],
    )
    assert msg.service == "iMessage"


def test_identifier_kind_constrained() -> None:
    Identifier(kind="email", value="a@b", is_primary=False)
    with pytest.raises(ValidationError):
        Identifier(kind="bogus", value="x", is_primary=False)  # type: ignore[arg-type]


def test_save_result_actions() -> None:
    SaveResult(action="inserted", message_id=1)
    SaveResult(action="skipped", message_id=1)
    SaveResult(action="updated", message_id=1)
    with pytest.raises(ValidationError):
        SaveResult(action="zzz", message_id=1)  # type: ignore[arg-type]
