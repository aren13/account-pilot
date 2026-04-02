"""RuleEngine — evaluate auto-tag rules against messages."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mailpilot.config import RuleConfig
    from mailpilot.database import Database
    from mailpilot.tags.manager import TagManager

logger = logging.getLogger(__name__)


class RuleEngine:
    """Evaluate auto-tag rules and apply matching actions."""

    def __init__(
        self,
        rules: list[RuleConfig],
        tag_manager: TagManager,
        db: Database,
    ) -> None:
        self.rules = rules
        self.tag_manager = tag_manager
        self.db = db

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def evaluate_message(
        self,
        mp_id: str,
        message: dict,
    ) -> None:
        """Evaluate all rules against a single message."""
        for rule in self.rules:
            if not self._simple_match(rule.match, message):
                continue

            adds: list[str] = []
            removes: list[str] = []

            for action in rule.actions:
                mode, tag = self._parse_action(action.tag)
                if mode == "add":
                    adds.append(tag)
                else:
                    removes.append(tag)

            if adds:
                await self.tag_manager.add_tags([mp_id], adds)
            if removes:
                await self.tag_manager.remove_tags(
                    [mp_id], removes
                )

            # Log to rule_log table
            actions_json = json.dumps(
                [a.tag for a in rule.actions]
            )
            msg = await self.db.get_message(mp_id)
            msg_row_id = msg["id"] if msg else None
            await self.db.conn.execute(
                "INSERT INTO rule_log "
                "(rule_name, message_id, actions) "
                "VALUES (?, ?, ?)",
                (rule.name, msg_row_id, actions_json),
            )
            await self.db.conn.commit()

            logger.info(
                "Rule '%s' fired on %s: %s",
                rule.name,
                mp_id,
                actions_json,
            )

    async def evaluate_batch(self, mp_ids: list[str]) -> None:
        """Evaluate all rules against a batch of messages."""
        for mp_id in mp_ids:
            msg = await self.db.get_message(mp_id)
            if msg is None:
                logger.warning(
                    "Message %s not found, skipping", mp_id
                )
                continue
            await self.evaluate_message(mp_id, msg)

    # ------------------------------------------------------------------
    # Pattern matching
    # ------------------------------------------------------------------

    def _simple_match(
        self, pattern: str, message: dict
    ) -> bool:
        """Match a simple pattern against a message dict.

        Supported patterns:
          - ``from:*@domain.com`` — from_address ends with @domain
          - ``from:exact@email.com`` — exact from_address match
          - ``to:*@domain.com`` — any to_address ends with @domain
          - ``to:exact@email.com`` — any to_address matches exactly

        Returns ``False`` for unrecognised patterns (no crash).
        """
        if ":" not in pattern:
            return False

        field, value = pattern.split(":", 1)
        field = field.strip().lower()
        value = value.strip()

        if field == "from":
            from_addr = (message.get("from_address") or "").lower()
            if value.startswith("*"):
                suffix = value[1:].lower()
                return from_addr.endswith(suffix)
            return from_addr == value.lower()

        if field == "to":
            to_raw = message.get("to_addresses") or "[]"
            if isinstance(to_raw, str):
                try:
                    to_list: list[str] = json.loads(to_raw)
                except (json.JSONDecodeError, TypeError):
                    to_list = [to_raw]
            else:
                to_list = list(to_raw)

            for addr in to_list:
                addr_lower = addr.lower()
                if value.startswith("*"):
                    suffix = value[1:].lower()
                    if addr_lower.endswith(suffix):
                        return True
                elif addr_lower == value.lower():
                    return True
            return False

        # Unrecognised field — skip gracefully
        return False

    # ------------------------------------------------------------------
    # Action parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_action(action_tag: str) -> tuple[str, str]:
        """Parse an action string into (mode, tag_name).

        ``"+urgent"`` → ``("add", "urgent")``
        ``"-inbox"``  → ``("remove", "inbox")``
        ``"urgent"``  → ``("add", "urgent")``
        """
        if action_tag.startswith("-"):
            return ("remove", action_tag[1:])
        if action_tag.startswith("+"):
            return ("add", action_tag[1:])
        return ("add", action_tag)
