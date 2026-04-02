"""MailPilot full-text search — Xapian indexer and query engine."""

from __future__ import annotations

try:
    import xapian  # noqa: F401

    HAS_XAPIAN = True
except ImportError:
    HAS_XAPIAN = False

from mailpilot.search.indexer import SearchIndexer
from mailpilot.search.query import SearchQuery

__all__ = ["HAS_XAPIAN", "SearchIndexer", "SearchQuery"]
