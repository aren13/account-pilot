"""SMTP exception hierarchy."""

from __future__ import annotations


class SmtpError(Exception):
    """Base exception for SMTP operations."""


class SmtpAuthError(SmtpError):
    """Raised when SMTP authentication fails."""
