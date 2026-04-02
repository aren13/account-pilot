"""MailPilot — Real-time email engine for AI agents."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mailpilot.config import AccountConfig, load_config
from mailpilot.database import Database
from mailpilot.events.emitter import EventEmitter
from mailpilot.events.types import EventType
from mailpilot.imap.client import ImapClient
from mailpilot.imap.parser import EmailParser
from mailpilot.search.threading import EmailThreader
from mailpilot.tags.manager import TagManager

if TYPE_CHECKING:
    from mailpilot.config import MailPilotConfig
    from mailpilot.search.indexer import SearchIndexer
    from mailpilot.search.query import SearchQuery

__version__ = "0.1.0"

logger = logging.getLogger(__name__)


class MailPilot:
    """Unified API for all MailPilot email operations.

    Provides a single entry point for search, read, send, and
    management operations across all configured email accounts.

    Usage::

        async with MailPilot(config_path) as mp:
            results = await mp.search("from:alice")
            await mp.mark_read([results[0]["mp_id"]])
    """

    def __init__(
        self, config_path: Path | None = None
    ) -> None:
        self._config: MailPilotConfig = load_config(config_path)
        self._db: Database | None = None
        self._search_query: SearchQuery | None = None
        self._search_indexer: SearchIndexer | None = None
        self._threader: EmailThreader | None = None
        self._tag_manager: TagManager | None = None
        self._event_emitter: EventEmitter | None = None
        self._imap_clients: dict[str, ImapClient] = {}
        self._smtp_clients: dict[str, Any] = {}
        self._parser: EmailParser = EmailParser()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Set up database, search, and per-account references."""
        data_dir = Path(self._config.mailpilot.data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)

        # Database
        self._db = Database(data_dir / "mailpilot.db")
        await self._db.initialize()

        # Search (optional — requires xapian)
        try:
            from mailpilot.search import HAS_XAPIAN

            if HAS_XAPIAN:
                from mailpilot.search import (
                    SearchIndexer,
                    SearchQuery,
                )

                index_path = data_dir / "xapian"
                stemmer = self._config.search.stemming
                self._search_query = SearchQuery(
                    index_path, stemmer
                )
                self._search_indexer = SearchIndexer(
                    index_path, stemmer
                )
        except Exception:
            logger.debug(
                "Xapian not available, full-text search disabled"
            )

        # Threading
        self._threader = EmailThreader()

        # Tags
        self._tag_manager = TagManager(
            db=self._db,
            indexer=self._search_indexer,
        )

        # Events
        webhook_urls: dict[str, str | None] = {}
        for acct in self._config.accounts:
            if acct.webhook_url:
                webhook_urls[acct.name] = acct.webhook_url
        self._event_emitter = EventEmitter(
            db=self._db, webhook_urls=webhook_urls
        )
        self._tag_manager.event_emitter = self._event_emitter

        # Per-account IMAP / SMTP references (lazy connect)
        for acct in self._config.accounts:
            self._imap_clients[acct.name] = ImapClient(
                account=acct,
                sync_config=self._config.sync,
            )
            # SmtpClient created lazily via _get_smtp_client

        # Ensure accounts exist in the database
        for acct in self._config.accounts:
            existing = await self._db.get_account(acct.name)
            if existing is None:
                await self._db.insert_account(
                    name=acct.name,
                    email=acct.email,
                    display_name=acct.display_name,
                    provider=acct.provider,
                )

        logger.info("MailPilot initialized (%s)", __version__)

    async def close(self) -> None:
        """Tear down all connections and resources."""
        for client in self._imap_clients.values():
            try:
                await client.disconnect()
            except Exception:
                logger.debug("IMAP disconnect error (ignored)")

        for client in self._smtp_clients.values():
            try:
                await client.close()
            except Exception:
                logger.debug("SMTP disconnect error (ignored)")

        if self._search_query is not None:
            self._search_query.close()
        if self._search_indexer is not None:
            self._search_indexer.close()
        if self._db is not None:
            await self._db.close()

        logger.info("MailPilot shut down")

    async def __aenter__(self) -> MailPilot:
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def db(self) -> Database:
        """Return the active database or raise."""
        if self._db is None:
            raise RuntimeError(
                "MailPilot not initialized — call initialize()"
            )
        return self._db

    @property
    def config(self) -> MailPilotConfig:
        """Return the loaded configuration."""
        return self._config

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "relevance",
    ) -> list[dict]:
        """Search messages by query string.

        Uses Xapian full-text search when available, otherwise
        falls back to a basic database search.
        """
        if self._search_query is not None:
            hits = await self._search_query.async_search(
                query, limit, offset, sort_by
            )
            mp_ids = [h["mp_id"] for h in hits]
            results: list[dict] = []
            for mp_id in mp_ids:
                msg = await self.db.get_message(mp_id)
                if msg is not None:
                    msg["tags"] = await self.db.get_message_tags(
                        msg["id"]
                    )
                    results.append(msg)
            return results

        # Fallback: database search
        return await self.db.search_messages(
            limit=limit, offset=offset
        )

    async def show(self, mp_id: str) -> dict:
        """Return a single message with body and tags.

        Reads the full body from Maildir when the message has a
        stored ``maildir_path``.
        """
        msg = await self.db.get_message(mp_id)
        if msg is None:
            raise KeyError(f"Message not found: {mp_id}")

        # Read body from Maildir if available
        maildir_path = msg.get("maildir_path")
        if maildir_path:
            path = Path(maildir_path)
            if path.exists():
                raw = path.read_bytes()
                plain, html = self._parser.parse_body(raw)
                msg["body_plain"] = plain
                msg["body_html"] = html

        msg["tags"] = await self.db.get_message_tags(msg["id"])
        return msg

    async def show_thread(
        self, thread_id: str
    ) -> list[dict]:
        """Return all messages in a thread, ordered by date."""
        messages = await self.db.get_messages_by_thread(
            thread_id
        )
        for msg in messages:
            msg["tags"] = await self.db.get_message_tags(
                msg["id"]
            )
        return messages

    async def list_unread(
        self,
        account: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """List unread messages, optionally filtered by account."""
        if self._search_query is not None:
            q = "tag:unread"
            if account:
                q += f" account:{account}"
            return await self.search(q, limit=limit)

        # Fallback: query db for messages tagged "unread"
        account_id = None
        if account:
            acct_row = await self.db.get_account(account)
            if acct_row:
                account_id = acct_row["id"]
        return await self.db.search_messages(
            account_id=account_id, limit=limit
        )

    async def count(self, query: str) -> int:
        """Count messages matching a query string."""
        if self._search_query is not None:
            return await self._search_query.async_count(query)
        # Fallback: count all non-deleted messages
        rows = await self.db.search_messages(limit=100_000)
        return len(rows)

    async def count_unread(self) -> dict:
        """Return per-account unread counts plus a total.

        Returns::

            {"accounts": {"work": 5, "personal": 2}, "total": 7}
        """
        result: dict[str, Any] = {"accounts": {}, "total": 0}
        for acct in self._config.accounts:
            acct_row = await self.db.get_account(acct.name)
            if acct_row is None:
                result["accounts"][acct.name] = 0
                continue
            # Count messages with the "unread" tag for this account
            cursor = await self.db.conn.execute(
                """
                SELECT COUNT(*) FROM messages m
                JOIN message_tags mt ON mt.message_id = m.id
                JOIN tags t ON t.id = mt.tag_id
                WHERE t.name = 'unread'
                  AND m.account_id = ?
                  AND m.is_deleted = 0
                """,
                (acct_row["id"],),
            )
            row = await cursor.fetchone()
            cnt: int = row[0]  # type: ignore[index]
            result["accounts"][acct.name] = cnt
            result["total"] += cnt
        return result

    async def events(
        self,
        event_type: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query stored events with optional filters."""
        if self._event_emitter is None:
            return []
        return await self._event_emitter.get_events(
            event_type=event_type, since=since, limit=limit
        )

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def send(
        self,
        account: str,
        to: list[str],
        subject: str,
        body: str,
        **kwargs: Any,
    ) -> str:
        """Compose and send an email via SMTP.

        Returns the generated Message-ID.
        """
        acct_cfg = self._get_account_config(account)
        smtp = await self._get_smtp_client(account)
        acct_row = await self.db.get_account(account)
        account_id = acct_row["id"] if acct_row else None

        message_id = await smtp.send(
            from_addr=acct_cfg.email,
            to=to,
            subject=subject,
            body=body,
            **kwargs,
        )

        if self._event_emitter is not None:
            await self._event_emitter.emit(
                EventType.EMAIL_SENT,
                account_id=account_id,
                details={
                    "to": to,
                    "subject": subject,
                    "message_id": message_id,
                },
            )

        return message_id

    async def reply(
        self,
        mp_id: str,
        body: str,
        reply_all: bool = False,
    ) -> str:
        """Reply to a message.

        Fetches the original message, constructs reply headers,
        and sends via the originating account's SMTP.
        """
        msg = await self.db.get_message(mp_id)
        if msg is None:
            raise KeyError(f"Message not found: {mp_id}")

        acct_cfg, _ = await self._get_account_for_message(
            mp_id
        )
        smtp = await self._get_smtp_client(acct_cfg.name)

        to_addrs = [msg["from_address"]]
        if reply_all:
            orig_to = json.loads(
                msg.get("to_addresses") or "[]"
            )
            orig_cc = json.loads(
                msg.get("cc_addresses") or "[]"
            )
            to_addrs.extend(orig_to)
            to_addrs.extend(orig_cc)
            # Remove self
            to_addrs = [
                a
                for a in to_addrs
                if a.lower() != acct_cfg.email.lower()
            ]

        subject = msg.get("subject") or ""
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"

        message_id = await smtp.send(
            from_addr=acct_cfg.email,
            to=to_addrs,
            subject=subject,
            body=body,
            in_reply_to=msg.get("message_id"),
            references=msg.get("references_hdr"),
        )

        if self._event_emitter is not None:
            acct_row = await self.db.get_account(acct_cfg.name)
            await self._event_emitter.emit(
                EventType.EMAIL_SENT,
                account_id=(
                    acct_row["id"] if acct_row else None
                ),
                details={
                    "reply_to": mp_id,
                    "message_id": message_id,
                },
            )

        return message_id

    async def forward(
        self,
        mp_id: str,
        to: list[str],
        body: str | None = None,
    ) -> str:
        """Forward a message to new recipients.

        Prepends the original message body below the optional
        user-supplied *body*.
        """
        msg = await self.db.get_message(mp_id)
        if msg is None:
            raise KeyError(f"Message not found: {mp_id}")

        acct_cfg, _ = await self._get_account_for_message(
            mp_id
        )
        smtp = await self._get_smtp_client(acct_cfg.name)

        original_body = msg.get("preview") or ""
        forward_body = (
            f"{body}\n\n---------- Forwarded ----------\n"
            f"{original_body}"
            if body
            else f"---------- Forwarded ----------\n"
            f"{original_body}"
        )

        subject = msg.get("subject") or ""
        if not subject.lower().startswith("fwd:"):
            subject = f"Fwd: {subject}"

        message_id = await smtp.send(
            from_addr=acct_cfg.email,
            to=to,
            subject=subject,
            body=forward_body,
        )

        if self._event_emitter is not None:
            acct_row = await self.db.get_account(acct_cfg.name)
            await self._event_emitter.emit(
                EventType.EMAIL_SENT,
                account_id=(
                    acct_row["id"] if acct_row else None
                ),
                details={
                    "forward_of": mp_id,
                    "to": to,
                    "message_id": message_id,
                },
            )

        return message_id

    # ------------------------------------------------------------------
    # Management operations
    # ------------------------------------------------------------------

    async def mark_read(self, mp_ids: list[str]) -> None:
        """Mark messages as read (IMAP + DB + event)."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                continue

            # Update IMAP flags
            acct_cfg, imap = await self._get_account_for_message(
                mp_id
            )
            await imap.set_flags(
                msg["folder"], [msg["uid"]], ["\\Seen"]
            )

            # Update DB flags
            flags = list(msg.get("flags") or [])
            if "\\Seen" not in flags:
                flags.append("\\Seen")
            await self.db.update_message(mp_id, flags=flags)

            # Remove unread tag
            if self._tag_manager is not None:
                await self._tag_manager.remove_tags(
                    [mp_id], ["unread"]
                )

            # Emit event
            if self._event_emitter is not None:
                await self._event_emitter.emit(
                    EventType.EMAIL_READ,
                    account_id=msg.get("account_id"),
                    message_id=msg["id"],
                    details={"mp_id": mp_id},
                )

    async def mark_unread(self, mp_ids: list[str]) -> None:
        """Mark messages as unread (IMAP + DB + event)."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                continue

            acct_cfg, imap = await self._get_account_for_message(
                mp_id
            )
            await imap.remove_flags(
                msg["folder"], [msg["uid"]], ["\\Seen"]
            )

            flags = [
                f
                for f in (msg.get("flags") or [])
                if f != "\\Seen"
            ]
            await self.db.update_message(mp_id, flags=flags)

            if self._tag_manager is not None:
                await self._tag_manager.add_tags(
                    [mp_id], ["unread"]
                )

            if self._event_emitter is not None:
                await self._event_emitter.emit(
                    EventType.EMAIL_READ,
                    account_id=msg.get("account_id"),
                    message_id=msg["id"],
                    details={
                        "mp_id": mp_id,
                        "action": "mark_unread",
                    },
                )

    async def flag(self, mp_ids: list[str]) -> None:
        """Flag (star) messages."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                continue

            _, imap = await self._get_account_for_message(
                mp_id
            )
            await imap.set_flags(
                msg["folder"], [msg["uid"]], ["\\Flagged"]
            )

            flags = list(msg.get("flags") or [])
            if "\\Flagged" not in flags:
                flags.append("\\Flagged")
            await self.db.update_message(mp_id, flags=flags)

            if self._tag_manager is not None:
                await self._tag_manager.add_tags(
                    [mp_id], ["flagged"]
                )

            if self._event_emitter is not None:
                await self._event_emitter.emit(
                    EventType.EMAIL_TAGGED,
                    account_id=msg.get("account_id"),
                    message_id=msg["id"],
                    details={
                        "mp_id": mp_id,
                        "action": "flag",
                    },
                )

    async def unflag(self, mp_ids: list[str]) -> None:
        """Remove flag (star) from messages."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                continue

            _, imap = await self._get_account_for_message(
                mp_id
            )
            await imap.remove_flags(
                msg["folder"], [msg["uid"]], ["\\Flagged"]
            )

            flags = [
                f
                for f in (msg.get("flags") or [])
                if f != "\\Flagged"
            ]
            await self.db.update_message(mp_id, flags=flags)

            if self._tag_manager is not None:
                await self._tag_manager.remove_tags(
                    [mp_id], ["flagged"]
                )

            if self._event_emitter is not None:
                await self._event_emitter.emit(
                    EventType.EMAIL_TAGGED,
                    account_id=msg.get("account_id"),
                    message_id=msg["id"],
                    details={
                        "mp_id": mp_id,
                        "action": "unflag",
                    },
                )

    async def move(
        self, mp_ids: list[str], to_folder: str
    ) -> None:
        """Move messages to a different IMAP folder."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                continue

            _, imap = await self._get_account_for_message(
                mp_id
            )
            await imap.move_messages(
                msg["folder"], [msg["uid"]], to_folder
            )

            await self.db.update_message(
                mp_id, folder=to_folder
            )

            if self._event_emitter is not None:
                await self._event_emitter.emit(
                    EventType.EMAIL_MOVED,
                    account_id=msg.get("account_id"),
                    message_id=msg["id"],
                    details={
                        "mp_id": mp_id,
                        "from_folder": msg["folder"],
                        "to_folder": to_folder,
                    },
                )

    async def delete(
        self,
        mp_ids: list[str],
        permanent: bool = False,
    ) -> None:
        """Delete messages (soft or permanent)."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                continue

            _, imap = await self._get_account_for_message(
                mp_id
            )
            await imap.delete_messages(
                msg["folder"],
                [msg["uid"]],
                permanent=permanent,
            )

            if permanent:
                await self.db.update_message(
                    mp_id, is_deleted=True
                )
            else:
                await self.db.delete_message(mp_id)

            if self._event_emitter is not None:
                await self._event_emitter.emit(
                    EventType.EMAIL_DELETED,
                    account_id=msg.get("account_id"),
                    message_id=msg["id"],
                    details={
                        "mp_id": mp_id,
                        "permanent": permanent,
                    },
                )

    async def tag(
        self,
        action: str,
        tags: list[str],
        mp_ids: list[str] | None = None,
        query: str | None = None,
    ) -> None:
        """Add or remove tags on messages by IDs or query.

        Args:
            action: ``"add"`` or ``"remove"``.
            tags: Tag names to add or remove.
            mp_ids: Explicit message IDs. Mutually exclusive
                with *query*.
            query: Search query to resolve message IDs.
        """
        if self._tag_manager is None:
            raise RuntimeError("MailPilot not initialized")

        target_ids: list[str] = []
        if mp_ids is not None:
            target_ids = list(mp_ids)
        elif query is not None:
            results = await self.search(query, limit=10_000)
            target_ids = [r["mp_id"] for r in results]
        else:
            raise ValueError(
                "Either mp_ids or query must be provided"
            )

        if action == "add":
            await self._tag_manager.add_tags(target_ids, tags)
        elif action == "remove":
            await self._tag_manager.remove_tags(
                target_ids, tags
            )
        else:
            raise ValueError(
                f"Invalid tag action: {action!r} "
                f"(expected 'add' or 'remove')"
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_account_config(
        self, account_name: str
    ) -> AccountConfig:
        """Look up an AccountConfig by name."""
        for acct in self._config.accounts:
            if acct.name == account_name:
                return acct
        raise KeyError(f"Account not found: {account_name}")

    async def _get_account_for_message(
        self, mp_id: str
    ) -> tuple[AccountConfig, ImapClient]:
        """Return the (AccountConfig, ImapClient) for a message."""
        msg = await self.db.get_message(mp_id)
        if msg is None:
            raise KeyError(f"Message not found: {mp_id}")

        acct_row = await self.db.get_account_by_id(
            msg["account_id"]
        )
        if acct_row is None:
            raise KeyError(
                f"Account not found for message: {mp_id}"
            )

        acct_name = acct_row["name"]
        acct_cfg = self._get_account_config(acct_name)
        imap = self._imap_clients.get(acct_name)
        if imap is None:
            raise KeyError(
                f"No IMAP client for account: {acct_name}"
            )
        return acct_cfg, imap

    async def _get_smtp_client(self, account: str) -> Any:
        """Return (or lazily create) the SMTP client for *account*."""
        if account in self._smtp_clients:
            return self._smtp_clients[account]

        # Import lazily — SmtpClient may be provided by a
        # parallel work stream.
        from mailpilot.smtp.client import SmtpClient

        acct_cfg = self._get_account_config(account)
        client = SmtpClient(acct_cfg)
        self._smtp_clients[account] = client
        return client
