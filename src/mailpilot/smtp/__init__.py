"""MailPilot SMTP client — async sending with aiosmtplib."""

from __future__ import annotations

from mailpilot.smtp.client import SmtpClient
from mailpilot.smtp.composer import EmailComposer
from mailpilot.smtp.exceptions import SmtpAuthError, SmtpError

__all__ = [
    "EmailComposer",
    "SmtpAuthError",
    "SmtpClient",
    "SmtpError",
]
