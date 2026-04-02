"""TagManager — add, remove, and query tags on messages."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mailpilot.database import Database
    from mailpilot.events.emitter import EventEmitter

logger = logging.getLogger(__name__)


class TagManager:
    """Manage tags on messages, with optional Xapian and event hooks."""

    def __init__(
        self,
        db: Database,
        indexer: Any = None,
        event_emitter: EventEmitter | None = None,
    ) -> None:
        self.db = db
        self.indexer = indexer
        self.event_emitter = event_emitter

    async def add_tags(
        self,
        mp_ids: list[str],
        tags: list[str],
    ) -> None:
        """Add *tags* to every message identified by *mp_ids*."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                logger.warning("Message %s not found, skipping", mp_id)
                continue

            msg_row_id: int = msg["id"]
            await self.db.add_message_tags(msg_row_id, tags)

            # Update Xapian index if available
            if self.indexer is not None:
                all_tags = await self.db.get_message_tags(msg_row_id)
                self.indexer.update_tags(mp_id, all_tags)

            # Emit event if available
            if self.event_emitter is not None:
                await self.event_emitter.emit(
                    "email_tagged",
                    account_id=msg.get("account_id"),
                    message_id=msg_row_id,
                    details={
                        "action": "add",
                        "tags": tags,
                        "mp_id": mp_id,
                    },
                )

        logger.debug(
            "Added tags %s to %d message(s)", tags, len(mp_ids)
        )

    async def remove_tags(
        self,
        mp_ids: list[str],
        tags: list[str],
    ) -> None:
        """Remove *tags* from every message identified by *mp_ids*."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                logger.warning("Message %s not found, skipping", mp_id)
                continue

            msg_row_id: int = msg["id"]
            await self.db.remove_message_tags(msg_row_id, tags)

            # Update Xapian index if available
            if self.indexer is not None:
                remaining = await self.db.get_message_tags(msg_row_id)
                self.indexer.update_tags(mp_id, remaining)

            # Emit event if available
            if self.event_emitter is not None:
                await self.event_emitter.emit(
                    "email_tagged",
                    account_id=msg.get("account_id"),
                    message_id=msg_row_id,
                    details={
                        "action": "remove",
                        "tags": tags,
                        "mp_id": mp_id,
                    },
                )

        logger.debug(
            "Removed tags %s from %d message(s)", tags, len(mp_ids)
        )

    async def get_tags(self, mp_id: str) -> list[str]:
        """Return all tag names for the message with *mp_id*."""
        msg = await self.db.get_message(mp_id)
        if msg is None:
            return []
        return await self.db.get_message_tags(msg["id"])

    async def list_tags(self) -> list[dict]:
        """Return all tags with their message counts."""
        return await self.db.list_tags()
