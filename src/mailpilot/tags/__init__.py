"""MailPilot tag system — manager and auto-tag rules engine."""

from __future__ import annotations

from mailpilot.tags.manager import TagManager
from mailpilot.tags.rules import RuleEngine

RESERVED_TAGS: frozenset[str] = frozenset(
    {
        "inbox",
        "unread",
        "sent",
        "draft",
        "trash",
        "spam",
        "flagged",
        "attachment",
    }
)

__all__ = ["RESERVED_TAGS", "RuleEngine", "TagManager"]
