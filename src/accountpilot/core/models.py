"""Pydantic v2 domain models shared between plugins and Storage."""

from __future__ import annotations

from datetime import (
    datetime,  # noqa: TC003 - needed for Pydantic v2 validation at runtime
)
from typing import Literal

from pydantic import BaseModel, ConfigDict

Direction = Literal["inbound", "outbound"]
IdentifierKind = Literal[
    "email",
    "phone",
    "imessage_handle",
    "telegram_username",
    "whatsapp_number",
]
IMessageService = Literal["iMessage", "SMS"]
SaveAction = Literal["inserted", "skipped", "updated"]
PersonRole = Literal["from", "to", "cc", "bcc", "participant"]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttachmentBlob(_StrictBase):
    filename: str
    content: bytes
    mime_type: str | None


class Identifier(_StrictBase):
    kind: IdentifierKind
    value: str
    is_primary: bool = False


class EmailMessage(_StrictBase):
    account_id: int
    external_id: str
    sent_at: datetime
    received_at: datetime | None
    direction: Direction
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    bcc_addresses: list[str]
    subject: str
    body_text: str
    body_html: str | None
    in_reply_to: str | None
    references: list[str]
    imap_uid: int
    mailbox: str
    gmail_thread_id: str | None
    labels: list[str]
    raw_headers: dict[str, str]
    attachments: list[AttachmentBlob]


class IMessageMessage(_StrictBase):
    account_id: int
    external_id: str
    sent_at: datetime
    direction: Direction
    sender_handle: str
    chat_guid: str
    participants: list[str]
    body_text: str
    service: IMessageService
    is_read: bool
    date_read: datetime | None
    attachments: list[AttachmentBlob]


class SaveResult(_StrictBase):
    action: SaveAction
    message_id: int
