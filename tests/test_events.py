"""Tests for the MailPilot event system."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from mailpilot.database import Database
from mailpilot.events import EventEmitter, EventType
from mailpilot.events.emitter import _parse_since

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def db():
    """Create an in-memory database, initialize it, yield, then close."""
    database = Database(Path(":memory:"))
    await database.initialize()
    yield database
    await database.close()


@pytest.fixture
def emitter(db: Database) -> EventEmitter:
    """Return an EventEmitter backed by the in-memory database."""
    return EventEmitter(db=db)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmitStoresInDb:
    """Verify events are persisted to the database."""

    @pytest.mark.asyncio
    async def test_emit_stores_in_db(
        self, emitter: EventEmitter, db: Database
    ) -> None:
        """Emit an event, query the database, verify it is stored."""
        await emitter.emit(
            EventType.NEW_EMAIL,
            account_id=1,
            message_id=42,
            details={"folder": "INBOX"},
        )

        events = await db.get_events(event_type="new_email")
        assert len(events) == 1
        assert events[0]["event_type"] == "new_email"
        assert events[0]["account_id"] == 1
        assert events[0]["message_id"] == 42
        assert '"folder"' in events[0]["details"]


class TestEmitCallsCallbacks:
    """Verify registered callbacks are invoked on emit."""

    @pytest.mark.asyncio
    async def test_emit_calls_callbacks(
        self, emitter: EventEmitter
    ) -> None:
        """Register a callback, emit an event, verify it was called."""
        cb = MagicMock()
        emitter.register_callback(cb)

        await emitter.emit(EventType.SYNC_STARTED, account_id=1)

        cb.assert_called_once_with(
            "sync_started", 1, None, None
        )


class TestCallbackErrorDoesntBreakOthers:
    """A failing callback must not prevent subsequent callbacks."""

    @pytest.mark.asyncio
    async def test_callback_error_doesnt_break_others(
        self, emitter: EventEmitter
    ) -> None:
        """First callback raises, second callback still fires."""
        bad_cb = MagicMock(side_effect=ValueError("boom"))
        good_cb = MagicMock()

        emitter.register_callback(bad_cb)
        emitter.register_callback(good_cb)

        await emitter.emit(EventType.ERROR, details={"msg": "oops"})

        bad_cb.assert_called_once()
        good_cb.assert_called_once()


class TestGetEventsByType:
    """Filter events by type when querying."""

    @pytest.mark.asyncio
    async def test_get_events_by_type(
        self, emitter: EventEmitter
    ) -> None:
        """Emit multiple types, filter returns only the requested type."""
        await emitter.emit(EventType.NEW_EMAIL, account_id=1)
        await emitter.emit(EventType.EMAIL_SENT, account_id=1)
        await emitter.emit(EventType.NEW_EMAIL, account_id=2)

        results = await emitter.get_events(
            event_type="new_email"
        )
        assert len(results) == 2
        for ev in results:
            assert ev["event_type"] == "new_email"


class TestGetEventsSinceRelative:
    """Test relative time filter on get_events."""

    @pytest.mark.asyncio
    async def test_get_events_since_relative(
        self, emitter: EventEmitter, db: Database
    ) -> None:
        """Events within the last hour are returned with '1h' filter."""
        # Insert an event directly with a known recent timestamp
        await emitter.emit(EventType.SYNC_COMPLETED, account_id=1)

        results = await emitter.get_events(since="1h")
        assert len(results) == 1

        # A very short window should still catch it (emitted just now)
        results = await emitter.get_events(since="1m")
        assert len(results) == 1


class TestGetEventsLimit:
    """Verify the limit parameter caps returned results."""

    @pytest.mark.asyncio
    async def test_get_events_limit(
        self, emitter: EventEmitter
    ) -> None:
        """Emit 10 events, query with limit=5, get exactly 5."""
        for i in range(10):
            await emitter.emit(
                EventType.NEW_EMAIL,
                account_id=1,
                message_id=i,
            )

        results = await emitter.get_events(limit=5)
        assert len(results) == 5


class TestParseSinceFormats:
    """Unit tests for the _parse_since helper."""

    def test_parse_since_formats(self) -> None:
        """'1h', '30m', '2d' each produce a datetime in the past."""
        now = datetime.now(UTC).replace(tzinfo=None)

        dt_1h = _parse_since("1h")
        assert now - dt_1h < timedelta(hours=1, seconds=5)
        assert now - dt_1h >= timedelta(minutes=59)

        dt_30m = _parse_since("30m")
        assert now - dt_30m < timedelta(minutes=30, seconds=5)
        assert now - dt_30m >= timedelta(minutes=29)

        dt_2d = _parse_since("2d")
        assert now - dt_2d < timedelta(days=2, seconds=5)
        assert now - dt_2d >= timedelta(days=1, hours=23)


class TestUnregisterCallback:
    """Verify that unregistered callbacks are no longer invoked."""

    @pytest.mark.asyncio
    async def test_unregister_callback(
        self, emitter: EventEmitter
    ) -> None:
        """Register, then unregister a callback; emit does not call it."""
        cb = MagicMock()
        emitter.register_callback(cb)
        emitter.unregister_callback(cb)

        await emitter.emit(EventType.EMAIL_DELETED, account_id=1)

        cb.assert_not_called()
