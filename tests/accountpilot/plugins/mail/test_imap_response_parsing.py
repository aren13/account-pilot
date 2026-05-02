"""Realistic-aioimaplib response parsing tests for ImapClient.

Two SP1 hardware-acceptance bugs were silent against the existing test
suite because FakeImapClient bypassed the real aioimaplib response
shape. These tests reproduce the actual shapes that `aioimaplib`'s
`uid_search` and `uid("fetch", …)` return so the same class of bug
fails loudly in unit tests next time.

Reference shapes captured from a live Gmail session:

  uid_search("ALL") response.lines = [
      b'177870 177877 ...',                # bytes (digit-only, no '* SEARCH ' prefix)
      b'SEARCH completed (Success)',
  ]

  uid("fetch", "180389", "(RFC822)") response.lines = [
      b'2209 FETCH (UID 180389 RFC822 {6331}',  # protocol envelope
      bytearray(b'<6331 bytes of RFC822>'),     # the payload (bytearray)
      b')',
      b'Success',
  ]
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock

import pytest

from accountpilot.plugins.mail.imap.client import ImapClient


@dataclass
class _FakeAioImapResponse:
    """Stand-in for aioimaplib.Response."""
    result: str
    lines: list[bytes | bytearray | str]


class _FakeAioImapConn:
    """Records calls and returns canned responses keyed by (verb, args)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.responses: dict[tuple[str, ...], _FakeAioImapResponse] = {}

    def queue(self, key: tuple[str, ...], response: _FakeAioImapResponse) -> None:
        self.responses[key] = response

    async def uid_search(self, criteria: str) -> _FakeAioImapResponse:
        self.calls.append(("uid_search", (criteria,)))
        return self.responses[("uid_search", criteria)]

    async def uid(self, *args: str) -> _FakeAioImapResponse:
        self.calls.append(("uid", args))
        return self.responses[("uid", *args)]


def _build_client_with_conn(conn: _FakeAioImapConn) -> ImapClient:
    """Construct a minimal ImapClient backed by `conn`, bypassing connect()."""
    from types import SimpleNamespace

    from accountpilot.plugins.mail.providers.gmail import GmailProvider

    account = SimpleNamespace(
        email="x@y.com",
        name="x",
        provider="gmail",
        imap=SimpleNamespace(
            host="imap.gmail.com", port=993, encryption="tls",
            auth=SimpleNamespace(method="password", password="pw"),
        ),
    )
    sync_cfg = SimpleNamespace(
        idle_timeout=60, reconnect_base_delay=1, reconnect_max_delay=5,
    )
    client = ImapClient(account=account, sync_config=sync_cfg)
    client._provider = GmailProvider()
    # Bypass ensure_connected (which would try to authenticate against the
    # real Gmail server) by stubbing _get_conn to return our fake directly.
    client._get_conn = AsyncMock(return_value=conn)  # type: ignore[method-assign]
    return client


# ─── fetch_uids ──────────────────────────────────────────────────────────


async def test_fetch_uids_decodes_bytes_response_lines() -> None:
    """Regression test: aioimaplib returns response.lines as bytes,
    not str. The legacy `if isinstance(line, str)` filter dropped them all
    and returned an empty UID list."""
    conn = _FakeAioImapConn()
    conn.queue(
        ("uid_search", "ALL"),
        _FakeAioImapResponse(
            result="OK",
            lines=[
                b"177870 177877 177879 177882 177884",
                b"SEARCH completed (Success)",
            ],
        ),
    )
    client = _build_client_with_conn(conn)

    uids = await client.fetch_uids("INBOX")

    assert uids == [177870, 177877, 177879, 177882, 177884]


async def test_fetch_uids_handles_multi_chunk_response() -> None:
    """Long mailboxes split the SEARCH response across multiple bytes
    chunks. Each chunk must be parsed independently."""
    conn = _FakeAioImapConn()
    conn.queue(
        ("uid_search", "ALL"),
        _FakeAioImapResponse(
            result="OK",
            lines=[
                b"100 101 102 103",
                b"104 105 106 107",
                b"108 109",
                b"SEARCH completed (Success)",
            ],
        ),
    )
    client = _build_client_with_conn(conn)

    uids = await client.fetch_uids("INBOX")

    assert uids == [100, 101, 102, 103, 104, 105, 106, 107, 108, 109]


async def test_fetch_uids_uid_range_when_since_uid_given() -> None:
    conn = _FakeAioImapConn()
    conn.queue(
        ("uid_search", "UID 101:*"),
        _FakeAioImapResponse(
            result="OK",
            lines=[b"101 102 103", b"SEARCH completed (Success)"],
        ),
    )
    client = _build_client_with_conn(conn)

    uids = await client.fetch_uids("INBOX", since_uid=100)

    assert uids == [101, 102, 103]


# ─── _fetch_part / fetch_message ─────────────────────────────────────────


async def test_fetch_message_returns_payload_not_envelope() -> None:
    """Regression test: aioimaplib FETCH response.lines starts with a
    protocol envelope line `b'<seq> FETCH (UID <n> RFC822 {<size>}'`,
    NOT the message body. The actual RFC822 lives in the next entry as
    bytearray. Returning the first bytes line gave us the envelope as
    the message body."""
    raw_email = (
        b"Message-ID: <abc@example.com>\r\n"
        b"From: foo@example.com\r\n"
        b"Subject: Hi\r\n"
        b"\r\n"
        b"Body text.\r\n"
    )
    conn = _FakeAioImapConn()
    conn.queue(
        ("uid", "fetch", "100", "(RFC822)"),
        _FakeAioImapResponse(
            result="OK",
            lines=[
                f"1 FETCH (UID 100 RFC822 {{{len(raw_email)}}}".encode(),
                bytearray(raw_email),
                b")",
                b"Success",
            ],
        ),
    )
    client = _build_client_with_conn(conn)

    payload = await client.fetch_message("INBOX", 100)

    assert payload == raw_email
    # Sanity: the envelope line is NOT what we returned.
    assert b"FETCH (UID" not in payload


async def test_fetch_headers_returns_payload_not_envelope() -> None:
    """Same shape as fetch_message but for RFC822.HEADER."""
    raw_headers = b"Message-ID: <a@b>\r\nSubject: Hi\r\n\r\n"
    conn = _FakeAioImapConn()
    conn.queue(
        ("uid", "fetch", "100", "(RFC822.HEADER)"),
        _FakeAioImapResponse(
            result="OK",
            lines=[
                f"1 FETCH (UID 100 RFC822.HEADER {{{len(raw_headers)}}}".encode(),
                bytearray(raw_headers),
                b")",
                b"Success",
            ],
        ),
    )
    client = _build_client_with_conn(conn)

    payload = await client.fetch_headers("INBOX", 100)

    assert payload == raw_headers


async def test_fetch_message_raises_on_non_ok_response() -> None:
    """Defensive: malformed/error responses must not silently return data."""
    conn = _FakeAioImapConn()
    conn.queue(
        ("uid", "fetch", "999", "(RFC822)"),
        _FakeAioImapResponse(
            result="NO",
            lines=[b"NO FETCH failed (Server says no)"],
        ),
    )
    client = _build_client_with_conn(conn)

    from accountpilot.plugins.mail.imap import ImapError
    with pytest.raises(ImapError):
        await client.fetch_message("INBOX", 999)
