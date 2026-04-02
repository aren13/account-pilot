"""Tests for the MailPilot tag manager and auto-tag rules engine."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
import pytest_asyncio

from mailpilot.config import RuleAction, RuleConfig
from mailpilot.database import Database
from mailpilot.tags import RESERVED_TAGS, RuleEngine, TagManager

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


@pytest_asyncio.fixture
async def tag_manager(db: Database) -> TagManager:
    """TagManager wired to in-memory db, no indexer or events."""
    return TagManager(db=db, indexer=None, event_emitter=None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _insert_account(db: Database, name: str = "test") -> int:
    return await db.insert_account(
        name=name,
        email=f"{name}@example.com",
        display_name="Test User",
    )


async def _insert_message(
    db: Database,
    account_id: int,
    uid: int = 1,
    folder: str = "INBOX",
    **overrides,
) -> tuple[int, str]:
    """Insert a test message. Returns (row_id, mp_id)."""
    defaults = dict(
        account_id=account_id,
        message_id=f"<msg-{uid}@example.com>",
        uid=uid,
        folder=folder,
        from_address="sender@example.com",
        to_addresses='["recipient@example.com"]',
        subject=f"Test subject {uid}",
        date=datetime(2025, 1, 1, 12, 0, 0).isoformat(),
    )
    defaults.update(overrides)
    row_id = await db.insert_message(**defaults)
    # mp_id is auto-generated as mp-NNNNNN
    msg = await db.conn.execute(
        "SELECT mp_id FROM messages WHERE id = ?", (row_id,)
    )
    row = await msg.fetchone()
    return row_id, row[0]


# ---------------------------------------------------------------------------
# Tag manager tests
# ---------------------------------------------------------------------------


class TestTagManager:
    """Tests for TagManager add/remove/get/list operations."""

    @pytest.mark.asyncio
    async def test_add_tags(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """Adding tags persists them and they appear in get_tags."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(db, acct)

        await tag_manager.add_tags([mp_id], ["work", "urgent"])

        tags = await tag_manager.get_tags(mp_id)
        assert sorted(tags) == ["urgent", "work"]

    @pytest.mark.asyncio
    async def test_remove_tags(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """Removing a tag leaves only the remaining tags."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(db, acct)

        await tag_manager.add_tags([mp_id], ["work", "urgent"])
        await tag_manager.remove_tags([mp_id], ["urgent"])

        tags = await tag_manager.get_tags(mp_id)
        assert tags == ["work"]

    @pytest.mark.asyncio
    async def test_get_tags(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """get_tags returns the correct sorted list."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(db, acct)

        await tag_manager.add_tags([mp_id], ["beta", "alpha"])

        tags = await tag_manager.get_tags(mp_id)
        assert tags == ["alpha", "beta"]

    @pytest.mark.asyncio
    async def test_list_tags_with_counts(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """list_tags returns all tags with correct message counts."""
        acct = await _insert_account(db)
        _, mp1 = await _insert_message(db, acct, uid=1)
        _, mp2 = await _insert_message(db, acct, uid=2)

        await tag_manager.add_tags([mp1, mp2], ["shared"])
        await tag_manager.add_tags([mp1], ["solo"])

        all_tags = await tag_manager.list_tags()
        by_name = {t["name"]: t for t in all_tags}

        assert by_name["shared"]["message_count"] == 2
        assert by_name["solo"]["message_count"] == 1

    @pytest.mark.asyncio
    async def test_add_tags_idempotent(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """Adding the same tag twice does not raise or duplicate."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(db, acct)

        await tag_manager.add_tags([mp_id], ["dup"])
        await tag_manager.add_tags([mp_id], ["dup"])

        tags = await tag_manager.get_tags(mp_id)
        assert tags == ["dup"]

    @pytest.mark.asyncio
    async def test_reserved_tags_constant(self) -> None:
        """RESERVED_TAGS contains all 8 expected system tags."""
        expected = {
            "inbox",
            "unread",
            "sent",
            "draft",
            "trash",
            "spam",
            "flagged",
            "attachment",
        }
        assert expected == RESERVED_TAGS
        assert isinstance(RESERVED_TAGS, frozenset)


# ---------------------------------------------------------------------------
# Rule engine tests
# ---------------------------------------------------------------------------


class TestRuleEngine:
    """Tests for RuleEngine pattern matching and action dispatch."""

    @pytest.mark.asyncio
    async def test_rule_adds_tag_on_match(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """A from:*@domain rule adds the configured tag."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(
            db,
            acct,
            from_address="alice@client.com",
        )

        rules = [
            RuleConfig(
                name="client-tag",
                match="from:*@client.com",
                actions=[RuleAction(tag="+client")],
            ),
        ]
        engine = RuleEngine(rules, tag_manager, db)
        msg = await db.get_message(mp_id)
        await engine.evaluate_message(mp_id, msg)

        tags = await tag_manager.get_tags(mp_id)
        assert "client" in tags

    @pytest.mark.asyncio
    async def test_rule_removes_tag(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """A rule with '-inbox' removes the inbox tag."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(
            db,
            acct,
            from_address="bot@newsletters.com",
        )

        # Pre-add inbox tag
        await tag_manager.add_tags([mp_id], ["inbox"])

        rules = [
            RuleConfig(
                name="no-inbox",
                match="from:*@newsletters.com",
                actions=[RuleAction(tag="-inbox")],
            ),
        ]
        engine = RuleEngine(rules, tag_manager, db)
        msg = await db.get_message(mp_id)
        await engine.evaluate_message(mp_id, msg)

        tags = await tag_manager.get_tags(mp_id)
        assert "inbox" not in tags

    @pytest.mark.asyncio
    async def test_rule_no_match_no_action(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """When no rule matches, no tags are changed."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(
            db,
            acct,
            from_address="nobody@other.com",
        )

        rules = [
            RuleConfig(
                name="miss",
                match="from:*@client.com",
                actions=[RuleAction(tag="+client")],
            ),
        ]
        engine = RuleEngine(rules, tag_manager, db)
        msg = await db.get_message(mp_id)
        await engine.evaluate_message(mp_id, msg)

        tags = await tag_manager.get_tags(mp_id)
        assert tags == []

    @pytest.mark.asyncio
    async def test_rule_logged(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """A fired rule creates an entry in the rule_log table."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(
            db,
            acct,
            from_address="alice@client.com",
        )

        rules = [
            RuleConfig(
                name="log-test",
                match="from:*@client.com",
                actions=[RuleAction(tag="+client")],
            ),
        ]
        engine = RuleEngine(rules, tag_manager, db)
        msg = await db.get_message(mp_id)
        await engine.evaluate_message(mp_id, msg)

        cursor = await db.conn.execute(
            "SELECT rule_name, actions FROM rule_log"
        )
        rows = await cursor.fetchall()
        assert len(rows) == 1
        assert rows[0][0] == "log-test"
        assert "+client" in rows[0][1]

    @pytest.mark.asyncio
    async def test_multiple_rules_evaluated(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """Multiple matching rules all apply their actions."""
        acct = await _insert_account(db)
        _, mp_id = await _insert_message(
            db,
            acct,
            from_address="alice@client.com",
        )

        rules = [
            RuleConfig(
                name="rule-a",
                match="from:*@client.com",
                actions=[RuleAction(tag="+client")],
            ),
            RuleConfig(
                name="rule-b",
                match="from:alice@client.com",
                actions=[RuleAction(tag="+alice")],
            ),
        ]
        engine = RuleEngine(rules, tag_manager, db)
        msg = await db.get_message(mp_id)
        await engine.evaluate_message(mp_id, msg)

        tags = await tag_manager.get_tags(mp_id)
        assert "client" in tags
        assert "alice" in tags

    @pytest.mark.asyncio
    async def test_simple_pattern_wildcard(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """Wildcard from:*@domain matches any user at that domain."""
        rules = [
            RuleConfig(
                name="w",
                match="from:*@example.org",
                actions=[RuleAction(tag="+org")],
            ),
        ]
        engine = RuleEngine(rules, tag_manager, db)

        # Should match
        assert engine._simple_match(
            "from:*@example.org",
            {"from_address": "anyone@example.org"},
        )
        # Should not match
        assert not engine._simple_match(
            "from:*@example.org",
            {"from_address": "anyone@other.com"},
        )

    @pytest.mark.asyncio
    async def test_evaluate_batch(
        self, db: Database, tag_manager: TagManager
    ) -> None:
        """evaluate_batch processes multiple messages."""
        acct = await _insert_account(db)
        _, mp1 = await _insert_message(
            db,
            acct,
            uid=1,
            from_address="a@client.com",
        )
        _, mp2 = await _insert_message(
            db,
            acct,
            uid=2,
            from_address="b@client.com",
        )
        _, mp3 = await _insert_message(
            db,
            acct,
            uid=3,
            from_address="c@other.com",
        )

        rules = [
            RuleConfig(
                name="batch-rule",
                match="from:*@client.com",
                actions=[RuleAction(tag="+client")],
            ),
        ]
        engine = RuleEngine(rules, tag_manager, db)
        await engine.evaluate_batch([mp1, mp2, mp3])

        assert "client" in await tag_manager.get_tags(mp1)
        assert "client" in await tag_manager.get_tags(mp2)
        assert "client" not in await tag_manager.get_tags(mp3)
