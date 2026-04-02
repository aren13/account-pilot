"""RFC822 email parser — extract Message-compatible fields from raw bytes."""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import mailparser

logger = logging.getLogger(__name__)

# Regex to extract angle-bracketed Message-IDs from References header.
_MSG_ID_RE = re.compile(r"<[^>]+>")


class EmailParser:
    """Parse raw RFC822 email bytes into MailPilot Message fields.

    Uses the ``mail-parser`` library for robust MIME handling and
    encoding detection, with additional helpers for References
    parsing and body extraction.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse_message(self, raw_bytes: bytes) -> dict[str, Any]:
        """Parse raw RFC822 *raw_bytes* into a dict of Message fields.

        The returned dict keys match the ``Message`` model (minus
        db-managed fields like ``id``, ``created_at``, etc.).
        All list-valued fields are JSON-encoded strings so they can
        be stored directly in SQLite.
        """
        try:
            mail = mailparser.parse_from_bytes(raw_bytes)
        except Exception:
            logger.exception("Failed to parse raw email bytes")
            return self._empty_result(raw_bytes)

        # -- sender ------------------------------------------------
        from_name, from_address = self._extract_sender(mail)

        # -- recipients --------------------------------------------
        to_addrs = self._extract_addresses(mail.to)
        cc_addrs = self._extract_addresses(mail.cc)
        bcc_addrs = self._extract_addresses(mail.bcc)

        # -- date --------------------------------------------------
        date_val = mail.date
        date_iso: str | None = None
        if date_val is not None:
            try:
                date_iso = date_val.isoformat()
            except Exception:
                logger.warning("Could not format date: %s", date_val)

        # -- references / in-reply-to ------------------------------
        refs_list = self.parse_references(
            mail.references if mail.references else None
        )
        in_reply_to = mail.in_reply_to or None
        if in_reply_to == "":
            in_reply_to = None

        # -- subject -----------------------------------------------
        subject = mail.subject or None

        # -- message-id --------------------------------------------
        message_id = mail.message_id or ""

        # -- body / preview ----------------------------------------
        plain, _html = self.parse_body(raw_bytes)
        preview: str | None = None
        if plain:
            preview = plain.strip()[:200]

        # -- attachments -------------------------------------------
        has_attachments = bool(mail.attachments)
        attachment_info = self._build_attachment_info(
            mail.attachments
        )

        return {
            "message_id": message_id,
            "from_address": from_address,
            "from_name": from_name or None,
            "to_addresses": json.dumps(to_addrs),
            "cc_addresses": (
                json.dumps(cc_addrs) if cc_addrs else None
            ),
            "bcc_addresses": (
                json.dumps(bcc_addrs) if bcc_addrs else None
            ),
            "subject": subject,
            "date": date_iso,
            "in_reply_to": in_reply_to,
            "references_hdr": (
                json.dumps(refs_list) if refs_list else None
            ),
            "preview": preview,
            "has_attachments": has_attachments,
            "attachment_info": (
                json.dumps(attachment_info)
                if attachment_info
                else None
            ),
            "size_bytes": len(raw_bytes),
        }

    def parse_body(
        self, raw_bytes: bytes
    ) -> tuple[str | None, str | None]:
        """Extract plain-text and HTML bodies from *raw_bytes*.

        Returns ``(plain_text, html_text)``.  Either value may be
        ``None`` if the corresponding part is absent.  Charset
        decoding is handled by ``mail-parser`` with graceful
        fallbacks.
        """
        try:
            mail = mailparser.parse_from_bytes(raw_bytes)
        except Exception:
            logger.exception("Failed to parse body from raw bytes")
            return None, None

        plain = self._join_parts(mail.text_plain)
        html = self._join_parts(mail.text_html)
        return plain, html

    def parse_references(
        self, header_value: str | None
    ) -> list[str]:
        """Parse a References header into a list of Message-IDs.

        Handles space-separated, newline-separated, and values
        with or without angle brackets.  Returns an empty list
        when *header_value* is ``None`` or empty.
        """
        if not header_value:
            return []

        # Try to extract angle-bracketed message-ids first.
        ids = _MSG_ID_RE.findall(header_value)
        if ids:
            return ids

        # Fallback: split on whitespace and filter blanks.
        parts = header_value.split()
        return [p for p in parts if p]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_sender(
        mail: mailparser.MailParser,
    ) -> tuple[str | None, str]:
        """Return ``(display_name, email_address)`` of the sender."""
        from_ = mail.from_
        if from_ and isinstance(from_, list) and from_[0]:
            name, addr = from_[0]
            return (name if name else None, addr or "")
        return None, ""

    @staticmethod
    def _extract_addresses(
        field: list[tuple[str, str]] | None,
    ) -> list[str]:
        """Extract a flat list of email addresses from a parsed field.

        ``mail-parser`` returns address fields as
        ``[(name, addr), ...]``.  Empty / placeholder entries
        (e.g. ``('', '')``) are filtered out.
        """
        if not field:
            return []
        return [
            addr
            for _name, addr in field
            if addr and addr.strip()
        ]

    @staticmethod
    def _build_attachment_info(
        attachments: list[dict[str, Any]],
    ) -> list[dict[str, Any]] | None:
        """Build a JSON-serialisable list of attachment metadata.

        Each entry contains ``filename``, ``content_type``, and
        ``size`` (estimated from the base64 payload when possible).
        """
        if not attachments:
            return None

        infos: list[dict[str, Any]] = []
        for att in attachments:
            filename = att.get("filename", "unknown")
            content_type = att.get(
                "mail_content_type", "application/octet-stream"
            )
            size = 0
            payload = att.get("payload", "")
            if payload and att.get("binary"):
                try:
                    size = len(base64.b64decode(payload))
                except Exception:
                    size = len(payload) * 3 // 4
            elif payload:
                size = len(payload.encode("utf-8", "replace"))
            infos.append(
                {
                    "filename": filename,
                    "content_type": content_type,
                    "size": size,
                }
            )
        return infos

    @staticmethod
    def _join_parts(parts: list[str] | None) -> str | None:
        """Join multiple MIME text parts into a single string."""
        if not parts:
            return None
        joined = "\n".join(parts).strip()
        return joined if joined else None

    @staticmethod
    def _empty_result(raw_bytes: bytes) -> dict[str, Any]:
        """Return a minimal dict when parsing fails entirely."""
        return {
            "message_id": "",
            "from_address": "",
            "from_name": None,
            "to_addresses": json.dumps([]),
            "cc_addresses": None,
            "bcc_addresses": None,
            "subject": None,
            "date": None,
            "in_reply_to": None,
            "references_hdr": None,
            "preview": None,
            "has_attachments": False,
            "attachment_info": None,
            "size_bytes": len(raw_bytes),
        }
