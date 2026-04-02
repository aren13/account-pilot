"""EventEmitter — emits events to SQLite, webhooks, and callbacks."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import urllib.request
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from mailpilot.database import Database
    from mailpilot.events.types import EventType

logger = logging.getLogger(__name__)


def _parse_since(since: str) -> datetime:
    """Parse a relative or ISO timestamp string into a datetime.

    Supports:
      - Relative: "30m", "1h", "2d" (minutes, hours, days)
      - ISO 8601: "2025-06-15T10:00:00"
    """
    match = re.fullmatch(r"(\d+)([mhd])", since)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        delta_map: dict[str, str] = {
            "m": "minutes",
            "h": "hours",
            "d": "days",
        }
        delta = timedelta(**{delta_map[unit]: value})
        return datetime.now(UTC).replace(tzinfo=None) - delta

    # Fall back to ISO 8601 parsing
    return datetime.fromisoformat(since)


def _fire_webhook(url: str, payload: dict[str, Any]) -> None:
    """Send a webhook POST (runs in a thread via asyncio.to_thread)."""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    urllib.request.urlopen(req, timeout=10)  # noqa: S310


class EventEmitter:
    """Emit events to the database, optional webhooks, and callbacks."""

    def __init__(
        self,
        db: Database,
        webhook_urls: dict[str, str | None] | None = None,
    ) -> None:
        self.db = db
        self.webhook_urls = webhook_urls or {}
        self._callbacks: list[Callable[..., Any]] = []

    async def emit(
        self,
        event_type: EventType | str,
        account_id: int | None = None,
        message_id: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Emit an event: persist to DB, fire webhook, call callbacks."""
        et = str(event_type)
        details_json = json.dumps(details) if details else None

        # 1. Persist to database
        await self.db.insert_event(
            account_id=account_id,
            event_type=et,
            message_id=message_id,
            details=details_json,
        )

        # 2. Fire webhook (fire-and-forget)
        url = self.webhook_urls.get(et)
        if url:
            payload = {
                "event_type": et,
                "account_id": account_id,
                "message_id": message_id,
                "details": details,
            }
            try:
                await asyncio.to_thread(_fire_webhook, url, payload)
            except Exception:
                logger.exception("Webhook failed for %s", et)

        # 3. Notify registered callbacks
        for cb in self._callbacks:
            try:
                cb(et, account_id, message_id, details)
            except Exception:
                logger.exception(
                    "Callback %s raised for event %s",
                    cb,
                    et,
                )

    def register_callback(
        self, callback: Callable[..., Any]
    ) -> None:
        """Register a callback to be invoked on every event."""
        self._callbacks.append(callback)

    def unregister_callback(
        self, callback: Callable[..., Any]
    ) -> None:
        """Remove a previously registered callback."""
        self._callbacks.remove(callback)

    async def get_events(
        self,
        event_type: str | None = None,
        since: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Query stored events with optional filters.

        Args:
            event_type: Filter by event type string.
            since: Relative ("1h", "30m", "2d") or ISO datetime.
            limit: Maximum number of events to return.
        """
        since_dt = _parse_since(since) if since else None
        return await self.db.get_events(
            event_type=event_type,
            since=since_dt,
            limit=limit,
        )
