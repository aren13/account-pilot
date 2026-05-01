"""Storage façade — the sole writer to the SQLite DB and CAS attachment store."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from accountpilot.core.identity import find_or_create_person
from accountpilot.core.models import (
    AttachmentBlob,
    EmailMessage,
    IMessageMessage,
    SaveResult,
)

if TYPE_CHECKING:
    import aiosqlite

    from accountpilot.core.cas import CASStore

# Match "Display Name <addr@host>" or bare "addr@host".
_RFC822_ADDR_RE = re.compile(
    r"^\s*(?:\"?(?P<name>[^<\"]*?)\"?\s*)?<?(?P<addr>[^<>\s]+@[^<>\s]+)>?\s*$"
)


def _split_address(raw: str) -> tuple[str, str | None]:
    """Return (email_address, display_name_or_None)."""
    m = _RFC822_ADDR_RE.match(raw)
    if m is None:
        return raw.strip(), None
    addr = m.group("addr").strip()
    name = (m.group("name") or "").strip() or None
    return addr, name


class Storage:
    """Sole writer to the AccountPilot DB and CAS."""

    def __init__(self, db: aiosqlite.Connection, cas: CASStore) -> None:
        self.db = db
        self.cas = cas

    async def save_email(self, msg: EmailMessage) -> SaveResult:
        # 1. CAS writes happen outside the DB transaction. Idempotent.
        cas_entries: list[tuple[AttachmentBlob, str, str]] = []
        for blob in msg.attachments:
            content_hash, cas_rel = self.cas.write(blob.content)
            cas_entries.append((blob, content_hash, cas_rel))

        # 2. Resolve all person_ids BEFORE the transaction so find_or_create_person's
        # internal commits don't interleave with our atomic save block.
        role_to_pid: list[tuple[int, str]] = []
        for raw, role in self._email_address_roles(msg):
            addr, display = _split_address(raw)
            pid = await find_or_create_person(
                self.db, kind="email", value=addr, default_name=display
            )
            role_to_pid.append((pid, role))

        # 3. DB transaction.
        await self.db.execute("BEGIN")
        try:
            # Dedup.
            async with self.db.execute(
                "SELECT id FROM messages WHERE account_id=? AND external_id=?",
                (msg.account_id, msg.external_id),
            ) as cur:
                existing = await cur.fetchone()
            if existing is not None:
                await self.db.execute("ROLLBACK")
                return SaveResult(action="skipped", message_id=int(existing["id"]))

            # Look up the account's source so messages.source stays in sync with
            # accounts.source.
            async with self.db.execute(
                "SELECT source FROM accounts WHERE id=?", (msg.account_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                await self.db.execute("ROLLBACK")
                raise ValueError(f"unknown account_id: {msg.account_id}")
            source = str(row["source"])

            # Insert message + email_details + message_people + attachments (no
            # nested commits — find_or_create_person calls already done).
            now = datetime.now(UTC).isoformat()
            cur2 = await self.db.execute(
                "INSERT INTO messages (account_id, source, external_id, thread_id, "
                "sent_at, received_at, body_text, body_html, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg.account_id,
                    source,
                    msg.external_id,
                    msg.gmail_thread_id,
                    msg.sent_at.isoformat(),
                    msg.received_at.isoformat() if msg.received_at else None,
                    msg.body_text,
                    msg.body_html,
                    msg.direction,
                    now,
                ),
            )
            message_id = cur2.lastrowid
            assert message_id is not None

            await self.db.execute(
                "INSERT INTO email_details (message_id, subject, in_reply_to, "
                "references_json, imap_uid, mailbox, gmail_thread_id, labels_json, "
                "raw_headers_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    msg.subject,
                    msg.in_reply_to,
                    json.dumps(msg.references),
                    msg.imap_uid,
                    msg.mailbox,
                    msg.gmail_thread_id,
                    json.dumps(msg.labels),
                    json.dumps(msg.raw_headers),
                ),
            )

            for pid, role in role_to_pid:
                await self.db.execute(
                    "INSERT OR IGNORE INTO message_people "
                    "(message_id, person_id, role) VALUES (?, ?, ?)",
                    (message_id, pid, role),
                )

            for blob, content_hash, cas_rel in cas_entries:
                await self.db.execute(
                    "INSERT INTO attachments (message_id, filename, content_hash, "
                    "mime_type, size_bytes, cas_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        message_id,
                        blob.filename,
                        content_hash,
                        blob.mime_type,
                        len(blob.content),
                        cas_rel,
                    ),
                )

            await self.db.execute("COMMIT")
            return SaveResult(action="inserted", message_id=message_id)
        except Exception:
            await self.db.execute("ROLLBACK")
            raise

    async def save_imessage(self, msg: IMessageMessage) -> SaveResult:
        # CAS writes (idempotent, outside DB transaction).
        cas_entries: list[tuple[AttachmentBlob, str, str]] = []
        for blob in msg.attachments:
            content_hash, cas_rel = self.cas.write(blob.content)
            cas_entries.append((blob, content_hash, cas_rel))

        # Resolve sender + participant person_ids BEFORE the transaction so
        # find_or_create_person's internal commits don't interleave.
        sender_pid = await find_or_create_person(
            self.db, kind="imessage_handle",
            value=msg.sender_handle, default_name=None,
        )
        participant_pids: list[int] = []
        for handle in msg.participants:
            pid = await find_or_create_person(
                self.db, kind="imessage_handle",
                value=handle, default_name=None,
            )
            participant_pids.append(pid)

        await self.db.execute("BEGIN")
        try:
            # Dedup.
            async with self.db.execute(
                "SELECT id FROM messages WHERE account_id=? AND external_id=?",
                (msg.account_id, msg.external_id),
            ) as cur:
                existing = await cur.fetchone()
            if existing is not None:
                await self.db.execute("ROLLBACK")
                return SaveResult(action="skipped", message_id=int(existing["id"]))

            # Look up source from accounts (don't hardcode).
            async with self.db.execute(
                "SELECT source FROM accounts WHERE id=?", (msg.account_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                await self.db.execute("ROLLBACK")
                raise ValueError(f"unknown account_id: {msg.account_id}")
            source = str(row["source"])

            now = datetime.now(UTC).isoformat()
            cur2 = await self.db.execute(
                "INSERT INTO messages (account_id, source, external_id, thread_id, "
                "sent_at, body_text, direction, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg.account_id, source, msg.external_id,
                    msg.chat_guid, msg.sent_at.isoformat(),
                    msg.body_text, msg.direction, now,
                ),
            )
            message_id = cur2.lastrowid
            assert message_id is not None

            await self.db.execute(
                "INSERT INTO imessage_details (message_id, chat_guid, service, "
                "is_from_me, is_read, date_read) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message_id, msg.chat_guid, msg.service,
                    1 if msg.direction == "outbound" else 0,
                    1 if msg.is_read else 0,
                    msg.date_read.isoformat() if msg.date_read else None,
                ),
            )

            await self.db.execute(
                "INSERT OR IGNORE INTO message_people (message_id, person_id, role) "
                "VALUES (?, ?, 'from')",
                (message_id, sender_pid),
            )
            for pid in participant_pids:
                await self.db.execute(
                    "INSERT OR IGNORE INTO message_people "
                    "(message_id, person_id, role) VALUES (?, ?, 'participant')",
                    (message_id, pid),
                )

            for blob, content_hash, cas_rel in cas_entries:
                await self.db.execute(
                    "INSERT INTO attachments (message_id, filename, content_hash, "
                    "mime_type, size_bytes, cas_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        message_id, blob.filename, content_hash, blob.mime_type,
                        len(blob.content), cas_rel,
                    ),
                )

            await self.db.execute("COMMIT")
            return SaveResult(action="inserted", message_id=message_id)
        except Exception:
            await self.db.execute("ROLLBACK")
            raise

    @staticmethod
    def _email_address_roles(msg: EmailMessage) -> list[tuple[str, str]]:
        roles: list[tuple[str, str]] = [(msg.from_address, "from")]
        for a in msg.to_addresses:
            roles.append((a, "to"))
        for a in msg.cc_addresses:
            roles.append((a, "cc"))
        for a in msg.bcc_addresses:
            roles.append((a, "bcc"))
        return roles
