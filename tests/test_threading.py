"""Tests for the JWZ email threading module."""

from __future__ import annotations

from mailpilot.search.threading import (
    EmailThreader,
    _generate_thread_id,
    _normalize_subject,
)


def _msg(
    message_id: str,
    subject: str = "Test",
    from_address: str = "alice@example.com",
    date: str = "2026-01-01T00:00:00",
    in_reply_to: str | None = None,
    references_hdr: str | None = None,
    to_addresses: str = '["bob@example.com"]',
) -> dict:
    """Build a minimal message dict for testing."""
    return {
        "message_id": message_id,
        "from_address": from_address,
        "to_addresses": to_addresses,
        "subject": subject,
        "date": date,
        "in_reply_to": in_reply_to,
        "references_hdr": references_hdr,
    }


# ------------------------------------------------------------------
# 1. Simple three-message thread
# ------------------------------------------------------------------

def test_simple_thread():
    msgs = [
        _msg("a@ex", subject="Hello", date="2026-01-01T10:00:00"),
        _msg(
            "b@ex",
            subject="Re: Hello",
            date="2026-01-01T11:00:00",
            in_reply_to="a@ex",
        ),
        _msg(
            "c@ex",
            subject="Re: Re: Hello",
            date="2026-01-01T12:00:00",
            in_reply_to="b@ex",
        ),
    ]
    threads = EmailThreader().thread_messages(msgs)
    assert len(threads) == 1
    t = threads[0]
    assert t["message_count"] == 3
    # Messages sorted ascending by date within thread
    ids = [m["message_id"] for m in t["messages"]]
    assert ids == ["a@ex", "b@ex", "c@ex"]


# ------------------------------------------------------------------
# 2. References chain
# ------------------------------------------------------------------

def test_references_chain():
    msgs = [
        _msg("r1@ex", subject="Topic", date="2026-01-01T10:00:00"),
        _msg("r2@ex", subject="Re: Topic", date="2026-01-01T11:00:00",
             in_reply_to="r1@ex",
             references_hdr='["r1@ex"]'),
        _msg("r3@ex", subject="Re: Topic", date="2026-01-01T12:00:00",
             in_reply_to="r2@ex",
             references_hdr='["r1@ex", "r2@ex"]'),
    ]
    threads = EmailThreader().thread_messages(msgs)
    assert len(threads) == 1
    assert threads[0]["message_count"] == 3


# ------------------------------------------------------------------
# 3. In-Reply-To only (no References)
# ------------------------------------------------------------------

def test_in_reply_to_only():
    msgs = [
        _msg("p@ex", subject="Question", date="2026-01-01T10:00:00"),
        _msg("q@ex", subject="Re: Question",
             date="2026-01-01T11:00:00",
             in_reply_to="p@ex"),
    ]
    threads = EmailThreader().thread_messages(msgs)
    assert len(threads) == 1
    assert threads[0]["message_count"] == 2


# ------------------------------------------------------------------
# 4. Separate threads
# ------------------------------------------------------------------

def test_separate_threads():
    msgs = [
        _msg("x@ex", subject="Alpha", date="2026-01-01T10:00:00"),
        _msg("y@ex", subject="Beta", date="2026-01-01T11:00:00"),
    ]
    threads = EmailThreader().thread_messages(msgs)
    assert len(threads) == 2


# ------------------------------------------------------------------
# 5. Subject fallback grouping
# ------------------------------------------------------------------

def test_subject_fallback():
    msgs = [
        _msg("s1@ex", subject="Meeting notes",
             date="2026-01-01T10:00:00"),
        _msg("s2@ex", subject="Re: Meeting notes",
             date="2026-01-01T11:00:00"),
    ]
    threads = EmailThreader().thread_messages(msgs)
    # Subject normalisation should match both to "meeting notes"
    assert len(threads) == 1
    assert threads[0]["message_count"] == 2


# ------------------------------------------------------------------
# 6. Subject normalisation
# ------------------------------------------------------------------

def test_subject_normalization():
    assert _normalize_subject(
        "Re: Re: Fwd: [list] Hello"
    ) == "hello"
    assert _normalize_subject("  RE: FWD: Test  ") == "test"
    assert _normalize_subject("[dev] Patch v2") == "patch v2"
    assert _normalize_subject("re: fwd: Re: ok") == "ok"


# ------------------------------------------------------------------
# 7. Thread ID is deterministic
# ------------------------------------------------------------------

def test_thread_id_deterministic():
    tid1 = _generate_thread_id("root@example.com")
    tid2 = _generate_thread_id("root@example.com")
    assert tid1 == tid2
    assert tid1.startswith("t-")
    # "t-" + 12 hex chars = 14 total
    assert len(tid1) == 14


# ------------------------------------------------------------------
# 8. Different roots → different thread IDs
# ------------------------------------------------------------------

def test_thread_id_different():
    tid1 = _generate_thread_id("aaa@example.com")
    tid2 = _generate_thread_id("bbb@example.com")
    assert tid1 != tid2


# ------------------------------------------------------------------
# 9. Empty container pruning
# ------------------------------------------------------------------

def test_empty_container_pruning():
    """A message references a missing parent — no crash, one thread."""
    msgs = [
        _msg("child@ex", subject="Re: Lost parent",
             date="2026-01-01T12:00:00",
             in_reply_to="ghost@ex"),
    ]
    threads = EmailThreader().thread_messages(msgs)
    assert len(threads) == 1
    assert threads[0]["message_count"] == 1
    assert threads[0]["messages"][0]["message_id"] == "child@ex"


# ------------------------------------------------------------------
# 10. Sort order: threads newest-first, messages oldest-first
# ------------------------------------------------------------------

def test_thread_sort_order():
    msgs = [
        _msg("old@ex", subject="Old topic",
             date="2026-01-01T08:00:00"),
        _msg("new@ex", subject="New topic",
             date="2026-01-02T08:00:00"),
        _msg("old2@ex", subject="Re: Old topic",
             date="2026-01-01T09:00:00",
             in_reply_to="old@ex"),
    ]
    threads = EmailThreader().thread_messages(msgs)
    assert len(threads) == 2
    # "New topic" thread is newer → first
    assert threads[0]["subject"] == "New topic"
    # "Old topic" thread messages sorted ascending
    old_thread = threads[1]
    dates = [m["date"] for m in old_thread["messages"]]
    assert dates == sorted(dates)


# ------------------------------------------------------------------
# 11. Participants are extracted and unique
# ------------------------------------------------------------------

def test_participants_extracted():
    msgs = [
        _msg("m1@ex", subject="Chat", date="2026-01-01T10:00:00",
             from_address="alice@ex"),
        _msg("m2@ex", subject="Re: Chat", date="2026-01-01T11:00:00",
             from_address="bob@ex", in_reply_to="m1@ex"),
        _msg("m3@ex", subject="Re: Chat", date="2026-01-01T12:00:00",
             from_address="alice@ex", in_reply_to="m2@ex"),
    ]
    threads = EmailThreader().thread_messages(msgs)
    assert len(threads) == 1
    participants = threads[0]["participants"]
    # Order preserved (alice first, then bob), no duplicates
    assert participants == ["alice@ex", "bob@ex"]
