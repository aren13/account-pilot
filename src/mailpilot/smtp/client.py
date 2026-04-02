"""Async SMTP client wrapping aiosmtplib."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiosmtplib

from mailpilot.config import resolve_password
from mailpilot.smtp.exceptions import SmtpAuthError, SmtpError

if TYPE_CHECKING:
    from email.message import EmailMessage

    from mailpilot.config import AccountConfig

logger = logging.getLogger(__name__)

# SMTP reply codes considered transient (worth retrying).
_TRANSIENT_CODES = {421, 450, 451, 452}

_MAX_RETRIES = 3


class SmtpClient:
    """Async SMTP client with TLS/STARTTLS support.

    Args:
        account: The account configuration (host, port, auth, etc.).
    """

    def __init__(self, account: AccountConfig) -> None:
        self._account = account
        self._smtp: aiosmtplib.SMTP | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Open an SMTP connection, negotiate TLS, and authenticate.

        Raises:
            SmtpAuthError: If login is rejected by the server.
            SmtpError: If the connection cannot be established.
        """
        cfg = self._account.smtp
        try:
            password = resolve_password(cfg.auth)
        except Exception as exc:
            raise SmtpAuthError(
                f"Failed to resolve password: {exc}"
            ) from exc

        use_tls = cfg.encryption == "tls"

        try:
            self._smtp = aiosmtplib.SMTP(
                hostname=cfg.host,
                port=cfg.port,
                use_tls=use_tls,
            )
            await self._smtp.connect()

            if cfg.encryption == "starttls":
                await self._smtp.starttls()

        except OSError as exc:
            raise SmtpError(
                f"Cannot connect to {cfg.host}:{cfg.port}: {exc}"
            ) from exc

        try:
            await self._smtp.login(self._account.email, password)
        except aiosmtplib.SMTPAuthenticationError as exc:
            raise SmtpAuthError(
                f"Login failed for {self._account.email}: {exc}"
            ) from exc
        except Exception as exc:
            raise SmtpAuthError(
                f"Login failed for {self._account.email}: {exc}"
            ) from exc

        logger.info("SMTP connected to %s:%d", cfg.host, cfg.port)

    async def send(self, message: EmailMessage) -> str:
        """Send an email message, retrying on transient failures.

        Args:
            message: A fully composed :class:`EmailMessage`.

        Returns:
            The Message-ID of the sent message.

        Raises:
            SmtpError: If sending fails after all retries.
        """
        if self._smtp is None:
            raise SmtpError("Not connected — call connect() first")

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                await self._smtp.send_message(message)
                msg_id = message["Message-ID"] or ""
                logger.info("Message sent: %s", msg_id)
                return msg_id
            except aiosmtplib.SMTPResponseException as exc:
                last_exc = exc
                if exc.code in _TRANSIENT_CODES:
                    logger.warning(
                        "Transient SMTP error (attempt %d/%d): %s",
                        attempt + 1,
                        _MAX_RETRIES,
                        exc,
                    )
                    continue
                raise SmtpError(
                    f"SMTP send failed: {exc}"
                ) from exc
            except Exception as exc:
                raise SmtpError(
                    f"SMTP send failed: {exc}"
                ) from exc

        raise SmtpError(
            f"SMTP send failed after {_MAX_RETRIES} retries: "
            f"{last_exc}"
        )

    async def disconnect(self) -> None:
        """Send QUIT and close the SMTP connection."""
        if self._smtp is not None:
            try:
                await self._smtp.quit()
            except Exception:
                logger.debug("SMTP QUIT error (ignored)")
            self._smtp = None
            logger.info("SMTP disconnected")

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> SmtpClient:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        await self.disconnect()
