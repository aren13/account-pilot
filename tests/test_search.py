"""Tests for the Xapian full-text search indexer and query engine."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from mailpilot.search import HAS_XAPIAN

# All tests are skipped when xapian bindings are not available.
pytestmark = pytest.mark.skipif(
    not HAS_XAPIAN, reason="xapian not available"
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture()
def xapian_dir(tmp_path: Path) -> Path:
    """Return a fresh temporary directory for a Xapian index."""
    return tmp_path / "xapian_index"


@pytest.fixture()
def sample_messages() -> list[tuple[dict, str, list[str]]]:
    """Five varied sample messages for testing.

    Each element is ``(msg_dict, body_text, tags)``.
    """
    return [
        (
            {
                "mp_id": "mp-001",
                "message_id": "<msg001@example.com>",
                "from_address": "alice@example.com",
                "to_addresses": json.dumps(
                    ["bob@example.com", "carol@example.com"]
                ),
                "cc_addresses": json.dumps(
                    ["dave@example.com"]
                ),
                "subject": "Meeting tomorrow morning",
                "folder": "INBOX",
                "account_name": "work",
                "has_attachments": False,
                "date": datetime(
                    2025, 6, 1, 9, 0, tzinfo=UTC
                ),
            },
            "Let's discuss the quarterly budget report.",
            ["inbox", "important"],
        ),
        (
            {
                "mp_id": "mp-002",
                "message_id": "<msg002@example.com>",
                "from_address": "bob@example.com",
                "to_addresses": json.dumps(
                    ["alice@example.com"]
                ),
                "cc_addresses": None,
                "subject": "Re: Meeting tomorrow morning",
                "folder": "INBOX",
                "account_name": "work",
                "has_attachments": True,
                "date": datetime(
                    2025, 6, 1, 10, 30, tzinfo=UTC
                ),
            },
            "Attached the slides for tomorrow's meeting.",
            ["inbox"],
        ),
        (
            {
                "mp_id": "mp-003",
                "message_id": "<msg003@example.com>",
                "from_address": "newsletter@shop.com",
                "to_addresses": json.dumps(
                    ["alice@example.com"]
                ),
                "cc_addresses": None,
                "subject": "Weekly deals and discounts",
                "folder": "Promotions",
                "account_name": "personal",
                "has_attachments": False,
                "date": datetime(
                    2025, 5, 28, 8, 0, tzinfo=UTC
                ),
            },
            "Check out our latest summer sale items.",
            ["promo", "unread"],
        ),
        (
            {
                "mp_id": "mp-004",
                "message_id": "<msg004@example.com>",
                "from_address": "ci@builds.dev",
                "to_addresses": json.dumps(
                    ["alice@example.com"]
                ),
                "cc_addresses": None,
                "subject": "Build failed: mailpilot#42",
                "folder": "Notifications",
                "account_name": "work",
                "has_attachments": False,
                "date": datetime(
                    2025, 6, 2, 14, 0, tzinfo=UTC
                ),
            },
            "The CI pipeline failed on commit abc123.",
            ["ci", "unread"],
        ),
        (
            {
                "mp_id": "mp-005",
                "message_id": "<msg005@example.com>",
                "from_address": "carol@example.com",
                "to_addresses": json.dumps(
                    ["alice@example.com"]
                ),
                "cc_addresses": json.dumps(
                    ["bob@example.com"]
                ),
                "subject": "Budget report final draft",
                "folder": "INBOX",
                "account_name": "work",
                "has_attachments": True,
                "date": datetime(
                    2025, 6, 3, 16, 0, tzinfo=UTC
                ),
            },
            "Please review the attached budget report.",
            ["inbox", "important", "review"],
        ),
    ]


@pytest.fixture()
def indexed_search(
    xapian_dir: Path,
    sample_messages: list[tuple[dict, str, list[str]]],
) -> tuple:
    """Index all samples, close writer, return (reader, dir)."""
    from mailpilot.search.indexer import SearchIndexer
    from mailpilot.search.query import SearchQuery

    writer = SearchIndexer(xapian_dir)
    for msg, body, tags in sample_messages:
        writer.index_message(msg, body, tags)
    writer.close()

    reader = SearchQuery(xapian_dir)
    return reader, xapian_dir


# ------------------------------------------------------------------
# Tests
# ------------------------------------------------------------------


def test_index_and_search_basic(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search("budget report")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-001" in mp_ids or "mp-005" in mp_ids
    reader.close()


def test_search_from_prefix(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search("from:alice@example.com")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-001" in mp_ids
    assert "mp-003" not in mp_ids
    reader.close()


def test_search_to_prefix(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search("to:bob@example.com")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-001" in mp_ids
    reader.close()


def test_search_tag_prefix(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search("tag:important")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-001" in mp_ids
    assert "mp-005" in mp_ids
    assert "mp-003" not in mp_ids
    reader.close()


def test_search_has_attachment(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search("has:attachment")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-002" in mp_ids
    assert "mp-005" in mp_ids
    assert "mp-001" not in mp_ids
    reader.close()


def test_search_boolean_and(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search("tag:inbox has:attachment")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-002" in mp_ids
    reader.close()


def test_search_boolean_not(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search("tag:inbox NOT has:attachment")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-001" in mp_ids
    assert "mp-002" not in mp_ids
    reader.close()


def test_search_limit_offset(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    all_results = reader.search("account:work", limit=100)
    limited = reader.search("account:work", limit=2, offset=0)
    assert len(limited) <= 2
    assert len(all_results) >= len(limited)
    reader.close()


def test_search_sort_by_date(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    results = reader.search(
        "account:work", sort_by="date", limit=10
    )
    assert len(results) > 0
    # The first result should be the most recent work message.
    assert results[0]["mp_id"] == "mp-004" or results[0][
        "mp_id"
    ] in {"mp-004", "mp-005"}
    reader.close()


def test_count(indexed_search: tuple) -> None:
    reader, _ = indexed_search
    n = reader.count("account:work")
    # mp-001, mp-002, mp-004, mp-005 are all "work"
    assert n >= 3
    reader.close()


def test_update_tags_reflected_in_search(
    xapian_dir: Path,
    sample_messages: list[tuple[dict, str, list[str]]],
) -> None:
    from mailpilot.search.indexer import SearchIndexer
    from mailpilot.search.query import SearchQuery

    writer = SearchIndexer(xapian_dir)
    for msg, body, tags in sample_messages:
        writer.index_message(msg, body, tags)

    # Update tags on mp-003 to include "important".
    writer.update_tags(
        "<msg003@example.com>", ["promo", "important"]
    )
    writer.close()

    reader = SearchQuery(xapian_dir)
    results = reader.search("tag:important")
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-003" in mp_ids
    reader.close()


def test_remove_message(
    xapian_dir: Path,
    sample_messages: list[tuple[dict, str, list[str]]],
) -> None:
    from mailpilot.search.indexer import SearchIndexer
    from mailpilot.search.query import SearchQuery

    writer = SearchIndexer(xapian_dir)
    for msg, body, tags in sample_messages:
        writer.index_message(msg, body, tags)

    writer.remove_message("<msg003@example.com>")
    writer.close()

    reader = SearchQuery(xapian_dir)
    results = reader.search("summer sale", limit=100)
    mp_ids = [r["mp_id"] for r in results]
    assert "mp-003" not in mp_ids
    reader.close()


def test_search_phrase(indexed_search: tuple) -> None:
    reader, _ = indexed_search
    results = reader.search('"budget report"')
    mp_ids = [r["mp_id"] for r in results]
    # Both mp-001 (body) and mp-005 (subject+body) mention it.
    assert len(mp_ids) >= 1
    reader.close()


def test_spelling_suggestion(
    indexed_search: tuple,
) -> None:
    reader, _ = indexed_search
    # Spelling correction depends on xapian's internal DB state.
    # We simply verify the method does not crash.
    result = reader.suggest_spelling("buget")
    # May or may not return a correction depending on DB.
    assert result is None or isinstance(result, str)
    reader.close()
