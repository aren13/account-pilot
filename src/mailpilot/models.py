"""MailPilot data models — Pydantic v2 models for all entities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Message(BaseModel):
    """A single email message stored in the local database."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    mp_id: str
    account_id: int
    message_id: str
    uid: int
    folder: str
    thread_id: str | None = None
    from_address: str
    from_name: str | None = None
    to_addresses: str  # JSON-encoded list
    cc_addresses: str | None = None
    bcc_addresses: str | None = None
    subject: str | None = None
    date: datetime
    in_reply_to: str | None = None
    references_hdr: str | None = None
    preview: str | None = None
    has_attachments: bool = False
    attachment_info: str | None = None  # JSON
    size_bytes: int | None = None
    flags: list[str] = Field(default_factory=list)
    maildir_path: str | None = None
    xapian_docid: int | None = None
    is_deleted: bool = False
    created_at: datetime
    updated_at: datetime

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> Message:
        """Construct from a plain dict (e.g. SQLite row)."""
        return cls.model_validate(data)


class Thread(BaseModel):
    """A conversation thread grouping related messages."""

    model_config = ConfigDict(from_attributes=True)

    thread_id: str
    subject: str
    messages: list[Message]
    participants: list[str]
    date: datetime  # latest message date
    message_count: int

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> Thread:
        """Construct from a plain dict."""
        return cls.model_validate(data)


class SearchResult(BaseModel):
    """A single result from a Xapian full-text search."""

    model_config = ConfigDict(from_attributes=True)

    mp_id: str
    message_id: str
    thread_id: str | None = None
    account: str
    from_address: str
    subject: str | None = None
    date: datetime
    tags: list[str]
    snippet: str
    has_attachments: bool
    relevance: float

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> SearchResult:
        """Construct from a plain dict."""
        return cls.model_validate(data)


class Event(BaseModel):
    """An audit/activity event logged by the system."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int | None = None
    event_type: str
    message_id: int | None = None
    details: str | None = None  # JSON
    created_at: datetime

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        """Construct from a plain dict."""
        return cls.model_validate(data)


class Tag(BaseModel):
    """A label that can be applied to messages."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    message_count: int = 0

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> Tag:
        """Construct from a plain dict."""
        return cls.model_validate(data)


class AccountStatus(BaseModel):
    """Runtime status snapshot for a configured email account."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    email: str
    is_active: bool
    connected: bool = False
    last_sync: datetime | None = None
    unread_count: int = 0

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> AccountStatus:
        """Construct from a plain dict."""
        return cls.model_validate(data)


class SendRequest(BaseModel):
    """Payload for composing and sending an email."""

    model_config = ConfigDict(from_attributes=True)

    account: str
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    html: str | None = None
    attachments: list[str] = Field(default_factory=list)
    in_reply_to: str | None = None
    references: list[str] = Field(default_factory=list)

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> SendRequest:
        """Construct from a plain dict."""
        return cls.model_validate(data)


class OutboxEntry(BaseModel):
    """A queued outbound email in the send pipeline."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    account_id: int
    to_addresses: str
    subject: str
    body_plain: str | None = None
    body_html: str | None = None
    status: Literal["pending", "sending", "sent", "failed"]
    error_message: str | None = None
    retry_count: int = 0
    created_at: datetime
    sent_at: datetime | None = None

    def to_json(self) -> dict:
        """Serialize to a JSON-compatible dict."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> OutboxEntry:
        """Construct from a plain dict."""
        return cls.model_validate(data)
