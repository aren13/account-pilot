"""Secrets resolution.

SP0 ships a no-op stub: Secrets is a wrapper over a dict the caller pre-populates.
SP1 replaces this with a real password_cmd + 1Password resolver.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Secrets:
    values: dict[str, str]

    def get(self, key: str) -> str | None:
        return self.values.get(key)
