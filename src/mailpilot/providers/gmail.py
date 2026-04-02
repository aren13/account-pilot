"""Gmail provider — IMAP folder aliases for Google Workspace / Gmail."""

from __future__ import annotations

import logging

from mailpilot.providers import Provider

logger = logging.getLogger(__name__)


class GmailProvider(Provider):
    """Provider with Gmail-specific IMAP folder mappings."""

    name = "gmail"
    _aliases: dict[str, str] = {
        "sent": "[Gmail]/Sent Mail",
        "trash": "[Gmail]/Trash",
        "drafts": "[Gmail]/Drafts",
        "spam": "[Gmail]/Spam",
        "archive": "[Gmail]/All Mail",
    }
