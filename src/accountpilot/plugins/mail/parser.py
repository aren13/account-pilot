"""RFC822 bytes → typed EmailMessage."""

from __future__ import annotations

import email
from datetime import UTC, datetime
from email import policy
from email.utils import parsedate_to_datetime
from typing import TYPE_CHECKING, Any, Literal, cast

from accountpilot.core.models import AttachmentBlob, EmailMessage

if TYPE_CHECKING:
    from email.message import Message as StdlibMessage


def parse_rfc822_to_email_message(
    *,
    raw_bytes: bytes,
    account_id: int,
    mailbox: str,
    imap_uid: int,
    direction: Literal["inbound", "outbound"],
    gmail_thread_id: str | None,
    labels: list[str],
) -> EmailMessage:
    """Parse RFC822 bytes into an EmailMessage Pydantic model.

    Caller supplies envelope metadata (account, mailbox, uid, direction,
    Gmail-specific labels/thread); this parser extracts content from the
    bytes themselves.
    """
    # Use compat32 policy to preserve raw header strings (e.g. quoted display
    # names like "Foo Bar" <foo@example.com> are not normalised away).
    parsed: StdlibMessage = email.message_from_bytes(
        raw_bytes, policy=policy.compat32
    )

    external_id = (parsed.get("Message-ID") or "").strip() or f"uid-{imap_uid}"
    sent_at = _parse_date(parsed.get("Date"))
    received_at = sent_at

    body_text, body_html, attachments = _walk_parts(parsed)

    return EmailMessage(
        account_id=account_id,
        external_id=external_id,
        sent_at=sent_at,
        received_at=received_at,
        direction=direction,
        from_address=str(parsed.get("From", "")).strip(),
        to_addresses=_split_address_list(parsed.get_all("To")),
        cc_addresses=_split_address_list(parsed.get_all("Cc")),
        bcc_addresses=_split_address_list(parsed.get_all("Bcc")),
        subject=str(parsed.get("Subject", "")).strip(),
        body_text=body_text,
        body_html=body_html,
        in_reply_to=_strip_or_none(parsed.get("In-Reply-To")),
        references=_split_message_id_list(parsed.get("References")),
        imap_uid=imap_uid,
        mailbox=mailbox,
        gmail_thread_id=gmail_thread_id,
        labels=labels,
        raw_headers={k: str(v) for k, v in parsed.items()},
        attachments=attachments,
    )


def _parse_date(raw: str | None) -> datetime:
    """RFC2822 → tz-aware datetime. Falls back to epoch UTC if unparseable."""
    if not raw:
        return datetime(1970, 1, 1, tzinfo=UTC)
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime(1970, 1, 1, tzinfo=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _strip_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _split_address_list(headers: list[Any] | None) -> list[str]:
    if not headers:
        return []
    out: list[str] = []
    for h in headers:
        for addr in str(h).split(","):
            a = addr.strip()
            if a:
                out.append(a)
    return out


def _split_message_id_list(raw: object) -> list[str]:
    """References / In-Reply-To header → list of <message-id> tokens."""
    if raw is None:
        return []
    return [
        tok
        for tok in str(raw).split()
        if tok.startswith("<") and tok.endswith(">")
    ]


def _walk_parts(
    parsed: StdlibMessage,
) -> tuple[str, str | None, list[AttachmentBlob]]:
    body_text: str = ""
    body_html: str | None = None
    attachments: list[AttachmentBlob] = []

    for part in parsed.walk():
        ctype = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()

        if part.is_multipart():
            continue

        if "attachment" in disposition or part.get_filename():
            raw_payload = cast("bytes", part.get_payload(decode=True) or b"")
            attachments.append(AttachmentBlob(
                filename=part.get_filename() or "attachment.bin",
                content=raw_payload,
                mime_type=ctype,
            ))
            continue

        charset = part.get_content_charset() or "utf-8"
        if ctype == "text/plain" and not body_text:
            raw_payload = cast("bytes", part.get_payload(decode=True) or b"")
            body_text = raw_payload.decode(charset, errors="replace")
        elif ctype == "text/html" and body_html is None:
            raw_payload = cast("bytes", part.get_payload(decode=True) or b"")
            body_html = raw_payload.decode(charset, errors="replace")

    return body_text, body_html, attachments
