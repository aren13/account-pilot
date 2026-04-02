"""Xapian query engine for MailPilot full-text search."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

try:
    import xapian

    HAS_XAPIAN = True
except ImportError:
    HAS_XAPIAN = False

logger = logging.getLogger(__name__)

# Boolean prefix mapping — maps user-facing prefixes to Xapian
# boolean term prefixes.
_BOOLEAN_PREFIXES: list[tuple[str, str]] = [
    ("from:", "XFROM:"),
    ("to:", "XTO:"),
    ("cc:", "XCC:"),
    ("subject:", "XSUBJECT:"),
    ("tag:", "XTAG:"),
    ("folder:", "XFOLDER:"),
    ("account:", "XACCOUNT:"),
    ("has:", "XHAS:"),
    ("msgid:", "XMSGID:"),
]


class SearchQuery:
    """Execute queries against a Xapian search index.

    The database is opened in **read-only** mode.
    """

    def __init__(
        self,
        index_path: Path,
        stemmer_language: str = "english",
    ) -> None:
        if not HAS_XAPIAN:
            msg = (
                "xapian Python bindings are not installed. "
                "Install the system-level xapian-bindings package."
            )
            raise RuntimeError(msg)

        self._index_path = index_path
        self._db = xapian.Database(str(index_path))
        self._stemmer_language = stemmer_language

        # Build a reusable QueryParser.
        self._qp = xapian.QueryParser()
        self._qp.set_stemmer(xapian.Stem(stemmer_language))
        self._qp.set_database(self._db)
        self._qp.set_stemming_strategy(
            xapian.QueryParser.STEM_SOME,
        )
        self._qp.set_default_op(xapian.Query.OP_AND)

        for user_prefix, term_prefix in _BOOLEAN_PREFIXES:
            self._qp.add_boolean_prefix(
                user_prefix.rstrip(":"), term_prefix
            )

        # Enable wildcards and spelling correction.
        self._flags = (
            xapian.QueryParser.FLAG_BOOLEAN
            | xapian.QueryParser.FLAG_PHRASE
            | xapian.QueryParser.FLAG_LOVEHATE
            | xapian.QueryParser.FLAG_WILDCARD
            | xapian.QueryParser.FLAG_SPELLING_CORRECTION
        )

    # ------------------------------------------------------------------
    # Synchronous API
    # ------------------------------------------------------------------

    def search(
        self,
        query_string: str,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "relevance",
    ) -> list[dict]:
        """Run *query_string* and return matching documents.

        Returns a list of ``{"mp_id": ..., "relevance": ...}`` dicts.
        """
        self._db.reopen()
        query = self._qp.parse_query(query_string, self._flags)
        enquire = xapian.Enquire(self._db)
        enquire.set_query(query)

        if sort_by == "date":
            # Slot 0 holds sortable-serialised timestamp.
            enquire.set_sort_by_value(0, True)  # reverse=True

        mset = enquire.get_mset(offset, limit)
        results: list[dict] = []
        for match in mset:
            results.append(
                {
                    "mp_id": match.document.get_data().decode(
                        "utf-8", errors="replace"
                    ),
                    "relevance": match.weight,
                }
            )
        return results

    def count(self, query_string: str) -> int:
        """Return the number of documents matching *query_string*."""
        self._db.reopen()
        query = self._qp.parse_query(query_string, self._flags)
        enquire = xapian.Enquire(self._db)
        enquire.set_query(query)
        # Request a large MSet to get the full count via
        # get_matches_estimated.
        mset = enquire.get_mset(0, 0)
        return mset.get_matches_estimated()

    def suggest_spelling(self, query_string: str) -> str | None:
        """Return a spelling-corrected query, or *None*."""
        self._db.reopen()
        self._qp.parse_query(query_string, self._flags)
        corrected = self._qp.get_corrected_query_string()
        if corrected and corrected != query_string:
            return corrected
        return None

    # ------------------------------------------------------------------
    # Async wrappers
    # ------------------------------------------------------------------

    async def async_search(
        self,
        query_string: str,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "relevance",
    ) -> list[dict]:
        """Async wrapper around :meth:`search`."""
        return await asyncio.to_thread(
            self.search, query_string, limit, offset, sort_by
        )

    async def async_count(self, query_string: str) -> int:
        """Async wrapper around :meth:`count`."""
        return await asyncio.to_thread(self.count, query_string)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying read-only database."""
        if self._db is not None:
            self._db.close()
            self._db = None  # type: ignore[assignment]
