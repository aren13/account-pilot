"""Email composer — build, send, reply, forward, and draft."""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import uuid
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mailpilot.config import AccountConfig
    from mailpilot.database import Database
    from mailpilot.events.emitter import EventEmitter
    from mailpilot.imap.client import ImapClient
    from mailpilot.models import SendRequest
    from mailpilot.smtp.client import SmtpClient

logger = logging.getLogger(__name__)

# Pattern to detect existing Re: / Fwd: prefixes (case-insensitive).
_RE_PREFIX = re.compile(r"^Re:\s*", re.IGNORECASE)
_FWD_PREFIX = re.compile(r"^Fwd?:\s*", re.IGNORECASE)


def _quote_body(body: str) -> str:
    """Prefix each line of *body* with ``> ``."""
    return "\n".join(f"> {line}" for line in body.splitlines())


def _make_message_id(domain: str) -> str:
    """Generate an RFC-compliant Message-ID."""
    unique = uuid.uuid4().hex[:16]
    return f"<{unique}@{domain}>"


class EmailComposer:
    """Compose, send, reply, forward, and draft emails.

    Args:
        db: Database instance for message lookups.
        smtp_client: Connected SMTP client for sending.
        imap_client: IMAP client for saving to Sent/Drafts.
        event_emitter: Optional event emitter for notifications.
        account: Account configuration for From/domain info.
    """

    def __init__(
        self,
        db: Database,
        smtp_client: SmtpClient,
        imap_client: ImapClient,
        event_emitter: EventEmitter | None = None,
        account: AccountConfig | None = None,
    ) -> None:
        self.db = db
        self.smtp_client = smtp_client
        self.imap_client = imap_client
        self.event_emitter = event_emitter
        self.account = account

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def compose_and_send(
        self, request: SendRequest
    ) -> str:
        """Build and send an email from a :class:`SendRequest`.

        Returns:
            The Message-ID of the sent message.
        """
        msg = self._build_message(request)

        # Send via SMTP
        message_id = await self.smtp_client.send(msg)

        # Save to Sent folder via IMAP
        sent_folder = "Sent"
        await self.imap_client.append_message(
            sent_folder,
            msg.as_bytes(),
            flags=["\\Seen"],
        )

        # Emit event
        if self.event_emitter is not None:
            await self.event_emitter.emit(
                "email_sent",
                details={
                    "message_id": message_id,
                    "to": request.to,
                    "subject": request.subject,
                },
            )

        return message_id

    async def reply(
        self,
        mp_id: str,
        body: str,
        reply_all: bool = False,
    ) -> str:
        """Reply to an existing message.

        Args:
            mp_id: The mp_id of the original message.
            body: Reply body text.
            reply_all: If True, include all original recipients.

        Returns:
            The Message-ID of the reply.
        """
        original = await self.db.get_message(mp_id)
        if original is None:
            msg = f"Message not found: {mp_id}"
            raise ValueError(msg)

        # Build recipients
        to_list = [original["from_address"]]
        cc_list: list[str] = []
        if reply_all and original.get("cc_addresses"):
            raw_cc = original["cc_addresses"]
            if isinstance(raw_cc, str):
                try:
                    cc_list = json.loads(raw_cc)
                except (json.JSONDecodeError, TypeError):
                    cc_list = [raw_cc]
            elif isinstance(raw_cc, list):
                cc_list = raw_cc

        # Build subject with Re: prefix (no double-prefix)
        orig_subject = original.get("subject") or ""
        if _RE_PREFIX.match(orig_subject):
            subject = orig_subject
        else:
            subject = f"Re: {orig_subject}"

        # Build In-Reply-To and References
        orig_msg_id = original.get("message_id") or ""
        in_reply_to = orig_msg_id
        refs_hdr = original.get("references_hdr") or ""
        references = (
            f"{refs_hdr} {orig_msg_id}" if refs_hdr else orig_msg_id
        )

        # Quote original body
        orig_body = original.get("preview") or ""
        quoted = _quote_body(orig_body)
        full_body = f"{body}\n\n{quoted}"

        from mailpilot.models import SendRequest

        request = SendRequest(
            account=self.account.name if self.account else "",
            to=to_list,
            cc=cc_list,
            subject=subject,
            body=full_body,
            in_reply_to=in_reply_to,
            references=references.split(),
        )

        message_id = await self.compose_and_send(request)

        # Set \Answered flag on original
        orig_folder = original.get("folder", "INBOX")
        orig_uid = original.get("uid")
        if orig_uid is not None:
            await self.imap_client.set_flags(
                orig_folder,
                [orig_uid],
                ["\\Answered"],
            )

        return message_id

    async def forward(
        self,
        mp_id: str,
        to: list[str],
        body: str | None = None,
    ) -> str:
        """Forward an existing message.

        Args:
            mp_id: The mp_id of the original message.
            to: Recipient addresses for the forward.
            body: Optional additional text to prepend.

        Returns:
            The Message-ID of the forwarded message.
        """
        original = await self.db.get_message(mp_id)
        if original is None:
            msg = f"Message not found: {mp_id}"
            raise ValueError(msg)

        # Build subject with Fwd: prefix (no double-prefix)
        orig_subject = original.get("subject") or ""
        if _FWD_PREFIX.match(orig_subject):
            subject = orig_subject
        else:
            subject = f"Fwd: {orig_subject}"

        # Build forwarded message header block
        orig_from = original.get("from_address", "")
        orig_date = original.get("date", "")
        orig_to_raw = original.get("to_addresses", "[]")
        if isinstance(orig_to_raw, str):
            try:
                orig_to_list = json.loads(orig_to_raw)
            except (json.JSONDecodeError, TypeError):
                orig_to_list = [orig_to_raw]
        else:
            orig_to_list = orig_to_raw
        orig_to_str = ", ".join(orig_to_list)

        fwd_header = (
            "---------- Forwarded message ----------\n"
            f"From: {orig_from}\n"
            f"Date: {orig_date}\n"
            f"Subject: {orig_subject}\n"
            f"To: {orig_to_str}\n"
        )

        orig_body = original.get("preview") or ""
        parts = [p for p in [body, fwd_header, orig_body] if p]
        full_body = "\n\n".join(parts)

        from mailpilot.models import SendRequest

        request = SendRequest(
            account=self.account.name if self.account else "",
            to=to,
            subject=subject,
            body=full_body,
        )

        return await self.compose_and_send(request)

    async def save_draft(self, request: SendRequest) -> str:
        """Save a message as a draft without sending.

        Returns:
            The Message-ID of the draft.
        """
        msg = self._build_message(request)
        message_id = msg["Message-ID"] or ""

        await self.imap_client.append_message(
            "Drafts",
            msg.as_bytes(),
            flags=["\\Draft", "\\Seen"],
        )

        return message_id

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_message(
        self, request: SendRequest
    ) -> EmailMessage:
        """Construct an :class:`EmailMessage` from a SendRequest."""
        msg = EmailMessage()

        # Domain for Message-ID generation
        domain = "mailpilot.local"
        if self.account:
            parts = self.account.email.split("@")
            if len(parts) == 2:  # noqa: PLR2004
                domain = parts[1]

        msg["Message-ID"] = _make_message_id(domain)
        msg["Date"] = datetime.now(UTC).strftime(
            "%a, %d %b %Y %H:%M:%S +0000"
        )

        # From
        if self.account:
            if self.account.display_name:
                msg["From"] = (
                    f"{self.account.display_name}"
                    f" <{self.account.email}>"
                )
            else:
                msg["From"] = self.account.email
        else:
            msg["From"] = request.account

        # Recipients
        msg["To"] = ", ".join(request.to)
        if request.cc:
            msg["Cc"] = ", ".join(request.cc)
        if request.bcc:
            msg["Bcc"] = ", ".join(request.bcc)

        msg["Subject"] = request.subject

        # Threading headers
        if request.in_reply_to:
            msg["In-Reply-To"] = request.in_reply_to
        if request.references:
            msg["References"] = " ".join(request.references)

        # Body
        msg.set_content(request.body)
        if request.html:
            msg.add_alternative(request.html, subtype="html")

        # Attachments
        for filepath in request.attachments:
            path = Path(filepath)
            mime, _ = mimetypes.guess_type(str(path))
            maintype, _, subtype = (mime or "application/octet-stream").partition("/")
            with open(path, "rb") as f:
                data = f.read()
            msg.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=path.name,
            )

        return msg
