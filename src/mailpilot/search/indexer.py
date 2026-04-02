"""Xapian full-text search indexer for MailPilot messages."""

from __future__ import annotations

import json
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


class SearchIndexer:
    """Index email messages into a Xapian database.

    The underlying ``WritableDatabase`` is opened lazily on first
    write so that construction is cheap and non-blocking.
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
        self._stemmer_language = stemmer_language
        self._db: xapian.WritableDatabase | None = None

        # Ensure the index directory exists.
        self._index_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Lazy database access
    # ------------------------------------------------------------------

    def _get_db(self) -> xapian.WritableDatabase:
        if self._db is None:
            self._db = xapian.WritableDatabase(
                str(self._index_path),
                xapian.DB_CREATE_OR_OPEN,
            )
        return self._db

    # ------------------------------------------------------------------
    # Indexing
    # ------------------------------------------------------------------

    def index_message(
        self,
        msg: dict,
        body_text: str,
        tags: list[str],
    ) -> int:
        """Index (or re-index) a single message.

        Returns the Xapian *docid* assigned to the document.
        """
        db = self._get_db()
        doc = xapian.Document()

        # Store mp_id as document data for retrieval.
        doc.set_data(msg["mp_id"])

        # ---- stemmed full-text indexing ----
        indexer = xapian.TermGenerator()
        indexer.set_stemmer(xapian.Stem(self._stemmer_language))
        indexer.set_document(doc)
        indexer.index_text(body_text)
        subject = msg.get("subject") or ""
        if subject:
            indexer.increase_termpos()
            indexer.index_text(subject)

        # ---- boolean (unstemmed, exact) terms ----
        from_addr = (msg.get("from_address") or "").lower()
        if from_addr:
            doc.add_boolean_term(f"XFROM:{from_addr}")

        for addr in _parse_address_list(msg.get("to_addresses")):
            doc.add_boolean_term(f"XTO:{addr}")

        for addr in _parse_address_list(msg.get("cc_addresses")):
            doc.add_boolean_term(f"XCC:{addr}")

        for word in subject.lower().split():
            doc.add_boolean_term(f"XSUBJECT:{word}")

        for tag in tags:
            doc.add_boolean_term(f"XTAG:{tag}")

        folder = msg.get("folder") or ""
        if folder:
            doc.add_boolean_term(f"XFOLDER:{folder}")

        account = msg.get("account_name") or ""
        if account:
            doc.add_boolean_term(f"XACCOUNT:{account}")

        if msg.get("has_attachments"):
            doc.add_boolean_term("XHAS:attachment")

        message_id = msg.get("message_id") or ""
        unique_term = f"XMSGID:{message_id}"
        if message_id:
            doc.add_boolean_term(unique_term)

        # ---- value slots for sorting / faceting ----
        date_val = msg.get("date")
        if date_val is not None:
            if isinstance(date_val, str):
                from datetime import UTC, datetime

                try:
                    dt = datetime.fromisoformat(date_val)
                except ValueError:
                    dt = datetime(1970, 1, 1, tzinfo=UTC)
                ts = dt.timestamp()
            else:
                ts = date_val.timestamp()
            doc.add_value(0, xapian.sortable_serialise(ts))

        doc.add_value(1, account)
        doc.add_value(2, from_addr)
        doc.add_value(3, subject)

        # ---- upsert via unique XMSGID term ----
        if message_id:
            db.replace_document(unique_term, doc)
            # Retrieve docid for the just-replaced document.
            enquire = xapian.Enquire(db)
            enquire.set_query(xapian.Query(unique_term))
            mset = enquire.get_mset(0, 1)
            docid = next(iter(mset)).docid if mset.size() else 0
        else:
            docid = db.add_document(doc)

        logger.debug("Indexed message %s as docid=%d", msg["mp_id"], docid)
        return docid

    # ------------------------------------------------------------------
    # Removal
    # ------------------------------------------------------------------

    def remove_message(self, message_id: str) -> None:
        """Delete a message from the index by its Message-ID."""
        db = self._get_db()
        unique_term = f"XMSGID:{message_id}"
        try:
            db.delete_document(unique_term)
            logger.debug("Removed message %s from index", message_id)
        except xapian.DocNotFoundError:
            logger.warning(
                "Attempted to remove non-existent message %s",
                message_id,
            )

    # ------------------------------------------------------------------
    # Tag updates
    # ------------------------------------------------------------------

    def update_tags(
        self,
        message_id: str,
        tags: list[str],
    ) -> None:
        """Replace all XTAG terms on a message with *tags*."""
        db = self._get_db()
        unique_term = f"XMSGID:{message_id}"

        # Find the document.
        postlist = db.postlist(unique_term)
        try:
            plitem = next(iter(postlist))
        except StopIteration:
            logger.warning(
                "Cannot update tags — message %s not in index",
                message_id,
            )
            return

        docid = plitem.docid
        doc = db.get_document(docid)

        # Remove existing XTAG: terms.
        to_remove: list[str] = []
        for termitem in doc:
            term = termitem.term
            if isinstance(term, bytes):
                term = term.decode("utf-8", errors="replace")
            if term.startswith("XTAG:"):
                to_remove.append(term)

        for term in to_remove:
            doc.remove_term(term)

        # Add new tags.
        for tag in tags:
            doc.add_boolean_term(f"XTAG:{tag}")

        db.replace_document(docid, doc)
        logger.debug(
            "Updated tags for message %s: %s", message_id, tags
        )

    # ------------------------------------------------------------------
    # Bulk reindex
    # ------------------------------------------------------------------

    def reindex(
        self,
        messages: list[tuple[dict, str, list[str]]],
    ) -> None:
        """Drop and rebuild the entire index from *messages*.

        Each element is a ``(msg_dict, body_text, tags)`` tuple.
        """
        db = self._get_db()
        # Wipe existing index.
        db.close()
        import shutil

        shutil.rmtree(self._index_path, ignore_errors=True)
        self._index_path.mkdir(parents=True, exist_ok=True)
        self._db = None  # force re-open

        for msg, body, tags in messages:
            self.index_message(msg, body, tags)

        logger.info("Reindexed %d messages", len(messages))

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Flush and close the underlying database."""
        if self._db is not None:
            self._db.close()
            self._db = None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _parse_address_list(raw: str | None) -> list[str]:
    """Parse a JSON-encoded address list, returning lowered addrs."""
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if isinstance(parsed, list):
        return [a.lower() for a in parsed if isinstance(a, str)]
    return []
