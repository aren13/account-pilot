"""JWZ email threading — groups messages into conversations.

Implements Jamie Zawinski's threading algorithm:
https://www.jwz.org/doc/threading.html

Operates on raw message dicts (from SQLite rows) and returns
thread dicts rather than Pydantic models to avoid coupling with
incomplete database records.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re

log = logging.getLogger(__name__)

# Patterns stripped during subject normalisation
_RE_PREFIX = re.compile(
    r"^(?:\s*(?:Re|RE|re|Fwd|FWD|fwd)\s*:\s*)+",
)
_LIST_TAG = re.compile(r"^\[[\w.+-]+\]\s*")


class Container:
    """Holder for a single Message-ID in the threading tree."""

    __slots__ = ("message_id", "message", "parent", "children")

    def __init__(self, message_id: str) -> None:
        self.message_id: str = message_id
        self.message: dict | None = None
        self.parent: Container | None = None
        self.children: list[Container] = []

    # ------------------------------------------------------------------
    def has_ancestor(self, other: Container) -> bool:
        """Return True if *other* is an ancestor of this container."""
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False


class EmailThreader:
    """Build conversation threads from a flat list of messages."""

    # ---- public API ---------------------------------------------------

    def thread_messages(
        self, messages: list[dict]
    ) -> list[dict]:
        """Apply JWZ threading and return thread dicts.

        Each returned dict contains:
            thread_id, subject, messages, participants, date,
            message_count
        """
        if not messages:
            return []

        id_table = self._build_id_table(messages)
        roots = self._find_root_set(id_table)
        roots = self._prune_empty(roots)
        roots = self._group_by_subject(roots)
        return self._build_threads(roots)

    # ---- Step 1: ID table ---------------------------------------------

    def _build_id_table(
        self, messages: list[dict]
    ) -> dict[str, Container]:
        id_table: dict[str, Container] = {}

        for msg in messages:
            mid = msg.get("message_id", "")
            if not mid:
                continue

            container = id_table.setdefault(mid, Container(mid))
            container.message = msg

            # Parse references chain
            refs = self._parse_references(msg)
            parent_ctr: Container | None = None

            for ref_id in refs:
                ref_ctr = id_table.setdefault(
                    ref_id, Container(ref_id)
                )
                # Link parent → child if not already linked
                if (
                    parent_ctr is not None
                    and ref_ctr.parent is None
                    and ref_ctr is not parent_ctr
                    and not parent_ctr.has_ancestor(ref_ctr)
                ):
                    ref_ctr.parent = parent_ctr
                    parent_ctr.children.append(ref_ctr)
                parent_ctr = ref_ctr

            # In-Reply-To is the direct parent of this message
            irt = msg.get("in_reply_to") or ""
            direct_parent_id = irt.strip() if irt else None
            if not direct_parent_id and refs:
                direct_parent_id = refs[-1]

            if direct_parent_id:
                dp_ctr = id_table.setdefault(
                    direct_parent_id, Container(direct_parent_id)
                )
                if (
                    container.parent is None
                    and container is not dp_ctr
                    and not dp_ctr.has_ancestor(container)
                ):
                    container.parent = dp_ctr
                    dp_ctr.children.append(container)

        return id_table

    # ---- Step 2: root set ---------------------------------------------

    @staticmethod
    def _find_root_set(
        id_table: dict[str, Container],
    ) -> list[Container]:
        return [c for c in id_table.values() if c.parent is None]

    # ---- Step 3: prune empties ----------------------------------------

    def _prune_empty(
        self, roots: list[Container]
    ) -> list[Container]:
        new_roots: list[Container] = []
        for root in roots:
            self._prune_container(root)
            # After pruning, the root itself might need handling
            if root.message is not None:
                new_roots.append(root)
            elif len(root.children) == 1:
                child = root.children[0]
                child.parent = None
                new_roots.append(child)
            elif root.children:
                # Keep as grouping node
                new_roots.append(root)
            # else: empty leaf — discard
        return new_roots

    def _prune_container(self, container: Container) -> None:
        """Recursively prune empty containers in the subtree."""
        i = 0
        while i < len(container.children):
            child = container.children[i]
            self._prune_container(child)

            if child.message is not None:
                i += 1
                continue

            if not child.children:
                # Empty leaf — remove
                container.children.pop(i)
                child.parent = None
                continue

            if len(child.children) == 1:
                # Promote sole grandchild
                grandchild = child.children[0]
                grandchild.parent = container
                container.children[i] = grandchild
                child.parent = None
                child.children.clear()
                # Re-check at same index
                continue

            # Multiple children — keep as grouping node
            i += 1

    # ---- Step 4: subject grouping -------------------------------------

    def _group_by_subject(
        self, roots: list[Container]
    ) -> list[Container]:
        subject_map: dict[str, Container] = {}

        for root in roots:
            subj = self._root_subject(root)
            if not subj:
                continue
            norm = _normalize_subject(subj)
            if not norm:
                continue
            existing = subject_map.get(norm)
            if existing is None:
                subject_map[norm] = root
            else:
                # Prefer the container that has a real message
                if existing.message is None and root.message is not None:
                    subject_map[norm] = root

        merged_roots: list[Container] = []
        seen: set[str] = set()

        for root in roots:
            if id(root) in seen:
                continue

            subj = self._root_subject(root)
            norm = _normalize_subject(subj) if subj else ""
            if not norm:
                seen.add(id(root))
                merged_roots.append(root)
                continue

            leader = subject_map.get(norm)
            if leader is None or leader is root:
                seen.add(id(root))
                merged_roots.append(root)
                continue

            if id(leader) not in seen:
                seen.add(id(leader))
                merged_roots.append(leader)

            # Merge root under leader
            seen.add(id(root))
            root.parent = leader
            leader.children.append(root)

        return merged_roots

    # ---- Step 5: build sorted thread dicts ----------------------------

    def _build_threads(
        self, roots: list[Container]
    ) -> list[dict]:
        threads: list[dict] = []
        for root in roots:
            flat = self._flatten(root)
            if not flat:
                continue
            threads.append(self._thread_dict(root, flat))

        # Sort threads: most recent message date descending
        threads.sort(key=lambda t: t["date"], reverse=True)
        return threads

    def _thread_dict(
        self, root: Container, flat: list[dict]
    ) -> dict:
        # Sort messages within thread by date ascending
        flat.sort(key=lambda m: m.get("date", ""))

        root_mid = root.message_id
        participants = list(
            dict.fromkeys(
                m["from_address"]
                for m in flat
                if m.get("from_address")
            )
        )
        latest_date = max(
            (m.get("date", "") for m in flat), default=""
        )
        subject = flat[0].get("subject") or ""

        return {
            "thread_id": _generate_thread_id(root_mid),
            "subject": subject,
            "messages": flat,
            "participants": participants,
            "date": latest_date,
            "message_count": len(flat),
        }

    # ---- helpers -------------------------------------------------------

    @staticmethod
    def _parse_references(msg: dict) -> list[str]:
        """Return an ordered list of Message-IDs from references_hdr."""
        raw = msg.get("references_hdr")
        if not raw:
            return []
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return [str(r) for r in parsed if r]
        except (json.JSONDecodeError, TypeError):
            pass
        return []

    @staticmethod
    def _root_subject(container: Container) -> str | None:
        """Walk the tree to find the first real subject."""
        if container.message and container.message.get("subject"):
            return container.message["subject"]
        for child in container.children:
            subj = EmailThreader._root_subject(child)
            if subj:
                return subj
        return None

    @staticmethod
    def _flatten(container: Container) -> list[dict]:
        """Collect all real messages under a container tree."""
        result: list[dict] = []
        stack = [container]
        while stack:
            node = stack.pop()
            if node.message is not None:
                result.append(node.message)
            stack.extend(reversed(node.children))
        return result


# ---- module-level helpers ---------------------------------------------


def _generate_thread_id(root_message_id: str) -> str:
    """Deterministic thread ID from the root Message-ID."""
    digest = hashlib.sha256(
        root_message_id.encode("utf-8")
    ).hexdigest()
    return f"t-{digest[:12]}"


def _normalize_subject(subject: str) -> str:
    """Strip reply/forward prefixes, list tags, and whitespace."""
    s = subject.strip()
    s = _RE_PREFIX.sub("", s)
    s = _LIST_TAG.sub("", s)
    # Second pass in case list tag was before Re:
    s = _RE_PREFIX.sub("", s)
    return s.strip().lower()
