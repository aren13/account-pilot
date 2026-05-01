"""Mail-plugin test fixtures: FakeImapClient for sync/plugin tests."""

from __future__ import annotations

import pytest  # noqa: F401  (kept for future fixture additions)


class FakeImapClient:
    """In-memory IMAP stand-in for sync orchestrator tests.

    Holds a mailbox→[(uid, raw_bytes)] map and exposes the subset of
    ImapClient methods sync.py uses.
    """

    def __init__(self, mailbox_data: dict[str, list[tuple[int, bytes]]]) -> None:
        self._data = mailbox_data
        self.connected_to: str | None = None

    async def connect(self, folder: str = "INBOX") -> None:
        self.connected_to = folder

    async def disconnect(self, folder: str | None = None) -> None:
        self.connected_to = None

    async def fetch_uids(self, folder: str, *, since_uid: int = 0) -> list[int]:
        return [u for (u, _) in self._data.get(folder, []) if u > since_uid]

    async def fetch_message(self, folder: str, uid: int) -> bytes:
        for (u, raw) in self._data.get(folder, []):
            if u == uid:
                return raw
        raise KeyError(f"uid {uid} not in {folder}")


def make_rfc822(uid: int) -> bytes:
    return (
        f"Message-ID: <synth-{uid}@example.com>\n"
        f"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        "From: Foo <foo@example.com>\n"
        "To: aren@example.com\n"
        f"Subject: Test {uid}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        f"body {uid}\n"
    ).encode()
