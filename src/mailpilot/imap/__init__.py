"""MailPilot IMAP client — async IMAP operations with aioimaplib."""

from __future__ import annotations


class ImapError(Exception):
    """Base exception for IMAP operations."""


class AuthenticationError(ImapError):
    """Raised when IMAP authentication fails."""


class ConnectionError(ImapError):  # noqa: A001
    """Raised when an IMAP connection cannot be established or is lost."""


__all__ = ["AuthenticationError", "ConnectionError", "ImapError"]
