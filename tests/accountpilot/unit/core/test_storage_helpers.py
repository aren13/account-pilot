from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from accountpilot.core.cas import CASStore
from accountpilot.core.models import EmailMessage, Identifier
from accountpilot.core.storage import Storage

if TYPE_CHECKING:
    from pathlib import Path

    import aiosqlite


async def test_upsert_owner_creates_then_returns_existing(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    pid1 = await storage.upsert_owner(
        name="Aren", surname="E",
        identifiers=[
            Identifier(kind="email", value="aren@x.com"),
            Identifier(kind="phone", value="+905052490139"),
        ],
    )
    pid2 = await storage.upsert_owner(
        name="Aren", surname="E",
        identifiers=[Identifier(kind="email", value="aren@x.com")],
    )
    assert pid1 == pid2

    async with tmp_db.execute(
        "SELECT is_owner FROM people WHERE id=?", (pid1,)
    ) as cur:
        assert (await cur.fetchone())["is_owner"] == 1  # type: ignore[index]


async def test_upsert_account_idempotent(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    owner_id = await storage.upsert_owner(
        name="Aren", surname=None,
        identifiers=[Identifier(kind="email", value="a@b.com")],
    )
    a1 = await storage.upsert_account(
        source="gmail", identifier="a@b.com", owner_id=owner_id,
        credentials_ref="op://x/y/z",
    )
    a2 = await storage.upsert_account(
        source="gmail", identifier="a@b.com", owner_id=owner_id,
        credentials_ref="op://x/y/z",
    )
    assert a1 == a2


async def test_latest_external_id_and_sent_at(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    owner_id = await storage.upsert_owner(
        name="A", surname=None,
        identifiers=[Identifier(kind="email", value="a@b.com")],
    )
    account_id = await storage.upsert_account(
        source="gmail", identifier="a@b.com", owner_id=owner_id,
    )
    assert await storage.latest_external_id(account_id) is None
    assert await storage.latest_sent_at(account_id) is None

    def _email(ext_id: str, sent: datetime) -> EmailMessage:
        return EmailMessage(
            account_id=account_id, external_id=ext_id, sent_at=sent,
            received_at=None, direction="inbound", from_address="z@z",
            to_addresses=[], cc_addresses=[], bcc_addresses=[],
            subject="", body_text="", body_html=None, in_reply_to=None,
            references=[], imap_uid=0, mailbox="INBOX",
            gmail_thread_id=None, labels=[], raw_headers={}, attachments=[],
        )

    await storage.save_email(_email("a", datetime(2026, 5, 1, tzinfo=UTC)))
    await storage.save_email(_email("b", datetime(2026, 5, 2, tzinfo=UTC)))
    assert await storage.latest_external_id(account_id) == "b"
    assert await storage.latest_sent_at(account_id) == datetime(2026, 5, 2, tzinfo=UTC)


async def test_upsert_owner_attaches_new_identifiers_to_matched_person(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    """When upsert_owner finds an existing person via one identifier, the OTHER
    identifiers in the list must attach to that same person (not create orphans)."""
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    pid1 = await storage.upsert_owner(
        name="Aren", surname="E",
        identifiers=[Identifier(kind="email", value="aren@x.com")],
    )
    # Re-run with the same email + a new phone. The phone must attach to pid1.
    pid2 = await storage.upsert_owner(
        name="Aren", surname="E",
        identifiers=[
            Identifier(kind="email", value="aren@x.com"),
            Identifier(kind="phone", value="+905052490139"),
        ],
    )
    assert pid1 == pid2

    async with tmp_db.execute(
        "SELECT person_id FROM identifiers WHERE kind='phone' AND value=?",
        ("+905052490139",),
    ) as cur:
        row = await cur.fetchone()
    assert row is not None, "phone identifier must exist"
    assert row["person_id"] == pid1, (
        f"phone must attach to existing owner #{pid1}, "
        f"not orphan person #{row['person_id']}"
    )

    # And there should still be exactly one person row total.
    async with tmp_db.execute("SELECT COUNT(*) AS c FROM people") as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["c"] == 1


async def test_upsert_owner_auto_merges_cross_person_collision(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    """When two declared identifiers point at two different existing people,
    upsert_owner consolidates them into one via merge_people."""
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))

    # Pre-seed two distinct people via find_or_create — these would normally
    # be two contacts created by save_email's address resolution.
    from accountpilot.core.identity import find_or_create_person
    person_a = await find_or_create_person(
        tmp_db, kind="email", value="aren@x.com", default_name="Aren"
    )
    person_b = await find_or_create_person(
        tmp_db, kind="phone", value="+15551234567", default_name="Aren"
    )
    assert person_a != person_b  # confirm the pre-seed split

    # Now declare them as the same owner. upsert_owner must merge.
    pid = await storage.upsert_owner(
        name="Aren", surname="E",
        identifiers=[
            Identifier(kind="email", value="aren@x.com"),
            Identifier(kind="phone", value="+15551234567"),
        ],
    )

    # Both identifiers now point at the same person.
    async with tmp_db.execute(
        "SELECT person_id FROM identifiers "
        "WHERE value IN ('aren@x.com', '+15551234567')"
    ) as cur:
        rows = [r["person_id"] for r in await cur.fetchall()]
    assert set(rows) == {pid}
    # And the duplicate person row is gone.
    async with tmp_db.execute(
        "SELECT COUNT(*) AS c FROM people"
    ) as cur:
        row = await cur.fetchone()
    assert row is not None
    assert row["c"] == 1
