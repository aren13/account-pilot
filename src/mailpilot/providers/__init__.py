"""MailPilot email provider abstractions."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_CANONICAL_FOLDERS = ("sent", "trash", "drafts", "spam", "archive")


class Provider:
    """Base class for email provider folder-name mappings.

    Subclasses override ``_aliases`` to map canonical folder names
    (sent, trash, drafts, spam, archive) to provider-specific IMAP
    folder paths.
    """

    name: str = "custom"
    _aliases: dict[str, str] = {}

    def folder_alias(self, name: str) -> str:
        """Resolve a canonical folder name to the provider-specific path.

        Args:
            name: Canonical folder name (e.g. "sent", "trash").

        Returns:
            The provider-specific IMAP folder name, or *name* unchanged
            if no alias is registered.
        """
        return self._aliases.get(name.lower(), name)

    @property
    def trash_folder(self) -> str:
        """Provider-specific trash folder name."""
        return self.folder_alias("trash")

    @property
    def sent_folder(self) -> str:
        """Provider-specific sent folder name."""
        return self.folder_alias("sent")


def get_provider(name: str) -> Provider:
    """Return a :class:`Provider` instance for *name*.

    Supported names: ``gmail``, ``outlook``, ``custom``.

    Args:
        name: Provider identifier from account config.

    Returns:
        A provider instance with the correct folder aliases.
    """
    # Lazy imports to avoid circular deps and keep the namespace clean.
    if name == "gmail":
        from mailpilot.providers.gmail import GmailProvider

        return GmailProvider()

    if name == "outlook":
        from mailpilot.providers.outlook import OutlookProvider

        return OutlookProvider()

    logger.debug("Using generic provider for '%s'", name)
    return Provider()


__all__ = ["Provider", "get_provider"]
