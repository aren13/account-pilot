"""Tests for the MailPilot SMTP client."""

from __future__ import annotations

from email.message import EmailMessage
from unittest.mock import AsyncMock, MagicMock, patch

import aiosmtplib
import pytest

from mailpilot.smtp import SmtpAuthError
from mailpilot.smtp.client import SmtpClient


def _make_account(encryption: str = "starttls") -> MagicMock:
    """Build a mock AccountConfig with the given encryption."""
    auth = MagicMock()
    auth.method = "password"
    auth.password_cmd = "echo secret"

    smtp_cfg = MagicMock()
    smtp_cfg.host = "smtp.example.com"
    smtp_cfg.port = 587 if encryption != "tls" else 465
    smtp_cfg.encryption = encryption
    smtp_cfg.auth = auth

    account = MagicMock()
    account.email = "user@example.com"
    account.smtp = smtp_cfg
    return account


class TestSmtpConnect:
    """Test SMTP connection negotiation."""

    @pytest.mark.asyncio
    @patch("mailpilot.smtp.client.resolve_password")
    @patch("mailpilot.smtp.client.aiosmtplib.SMTP")
    async def test_connect_tls(
        self,
        mock_smtp_cls: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        """TLS mode should set use_tls=True."""
        mock_resolve.return_value = "secret"
        mock_instance = AsyncMock()
        mock_smtp_cls.return_value = mock_instance

        account = _make_account("tls")
        client = SmtpClient(account)
        await client.connect()

        mock_smtp_cls.assert_called_once_with(
            hostname="smtp.example.com",
            port=465,
            use_tls=True,
        )
        mock_instance.connect.assert_awaited_once()
        mock_instance.starttls.assert_not_awaited()
        mock_instance.login.assert_awaited_once_with(
            "user@example.com", "secret"
        )

    @pytest.mark.asyncio
    @patch("mailpilot.smtp.client.resolve_password")
    @patch("mailpilot.smtp.client.aiosmtplib.SMTP")
    async def test_connect_starttls(
        self,
        mock_smtp_cls: MagicMock,
        mock_resolve: MagicMock,
    ) -> None:
        """STARTTLS mode should call starttls() after connect."""
        mock_resolve.return_value = "secret"
        mock_instance = AsyncMock()
        mock_smtp_cls.return_value = mock_instance

        account = _make_account("starttls")
        client = SmtpClient(account)
        await client.connect()

        mock_smtp_cls.assert_called_once_with(
            hostname="smtp.example.com",
            port=587,
            use_tls=False,
        )
        mock_instance.connect.assert_awaited_once()
        mock_instance.starttls.assert_awaited_once()
        mock_instance.login.assert_awaited_once_with(
            "user@example.com", "secret"
        )


class TestSmtpSend:
    """Test message sending and retry logic."""

    @pytest.mark.asyncio
    async def test_send_message(self) -> None:
        """send() should call send_message and return Message-ID."""
        account = _make_account()
        client = SmtpClient(account)
        client._smtp = AsyncMock()

        msg = EmailMessage()
        msg["Message-ID"] = "<test123@example.com>"
        msg["To"] = "to@example.com"
        msg.set_content("Hello")

        result = await client.send(msg)

        client._smtp.send_message.assert_awaited_once_with(msg)
        assert result == "<test123@example.com>"

    @pytest.mark.asyncio
    async def test_retry_on_transient_error(self) -> None:
        """send() retries on transient SMTP errors then succeeds."""
        account = _make_account()
        client = SmtpClient(account)
        client._smtp = AsyncMock()

        # First call raises transient 451, second succeeds.
        transient = aiosmtplib.SMTPResponseException(
            451, "Try again"
        )
        client._smtp.send_message.side_effect = [
            transient,
            None,
        ]

        msg = EmailMessage()
        msg["Message-ID"] = "<retry@example.com>"
        msg.set_content("Hello")

        result = await client.send(msg)
        assert result == "<retry@example.com>"
        assert client._smtp.send_message.await_count == 2

    @pytest.mark.asyncio
    async def test_auth_error_raised(self) -> None:
        """SmtpAuthError is raised when authentication fails."""
        account = _make_account()
        client = SmtpClient(account)
        client._smtp = AsyncMock()

        # Simulate a non-transient auth error during login.
        with (
            patch(
                "mailpilot.smtp.client.resolve_password"
            ) as mock_resolve,
            patch(
                "mailpilot.smtp.client.aiosmtplib.SMTP"
            ) as mock_cls,
        ):
            mock_resolve.return_value = "bad"
            mock_instance = AsyncMock()
            mock_cls.return_value = mock_instance
            mock_instance.login.side_effect = (
                aiosmtplib.SMTPAuthenticationError(
                    535, "Auth failed"
                )
            )

            fresh_client = SmtpClient(account)
            with pytest.raises(SmtpAuthError, match="Login failed"):
                await fresh_client.connect()
