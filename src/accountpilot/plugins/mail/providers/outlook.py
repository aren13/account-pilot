"""Outlook provider — IMAP folder aliases for Microsoft 365 / Outlook."""

from __future__ import annotations

import logging

from accountpilot.plugins.mail.providers import Provider

logger = logging.getLogger(__name__)


class OutlookProvider(Provider):
    """Provider with Outlook-specific IMAP folder mappings."""

    name = "outlook"
    _aliases: dict[str, str] = {
        "sent": "Sent Items",
        "trash": "Deleted Items",
        "drafts": "Drafts",
        "spam": "Junk Email",
        "archive": "Archive",
    }
