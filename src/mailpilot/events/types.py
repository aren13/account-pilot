"""Event type definitions for the MailPilot event system."""

from __future__ import annotations

from enum import StrEnum


class EventType(StrEnum):
    """All event types emitted by MailPilot."""

    # Message lifecycle
    NEW_EMAIL = "new_email"
    EMAIL_READ = "email_read"
    EMAIL_SENT = "email_sent"
    EMAIL_DELETED = "email_deleted"
    EMAIL_MOVED = "email_moved"
    EMAIL_TAGGED = "email_tagged"

    # Sync lifecycle
    SYNC_STARTED = "sync_started"
    SYNC_COMPLETED = "sync_completed"

    # System
    ERROR = "error"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_RESTORED = "connection_restored"
