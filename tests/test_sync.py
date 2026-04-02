"""Tests for the Maildir manager and IMAP sync engine."""

from __future__ import annotations

import email
import email.utils
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio

from mailpilot.config import (
    AccountConfig,
    AuthConfig,
    FolderConfig,
    ImapConfig,
    SmtpConfig,
)
from mailpilot.database import Database
from mailpilot.imap.parser import EmailParser
from mailpilot.imap.sync import MaildirManager, SyncEngine

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def maildir_path(tmp_path: Path) -> Path:
    """Return a temporary directory to use as the Maildir base."""
    return tmp_path / "maildir"


@pytest_asyncio.fixture
async def db(tmp_path: Path) -> Database:
    """Create an in-memory database, initialize it, yield, then close."""
    database = Database(Path(":memory:"))
    await database.initialize()
    yield database  # type: ignore[misc]
    await database.close()


@pytest.fixture
def sample_account() -> AccountConfig:
    """Return a minimal AccountConfig for testing."""
    return AccountConfig(
        name="testacct",
        email="test@example.com",
        display_name="Test User",
        provider="custom",
        imap=ImapConfig(
            host="imap.example.com",
            port=993,
            encryption="tls",
            auth=AuthConfig(
                method="password", password_cmd="echo secret"
            ),
        ),
        smtp=SmtpConfig(
            host="smtp.example.com",
            port=587,
            encryption="starttls",
            auth=AuthConfig(
                method="password", password_cmd="echo secret"
            ),
        ),
        folders=FolderConfig(sync=["INBOX"]),
    )


@pytest.fixture
def sample_raw_email() -> bytes:
    """Build a simple RFC822 email as raw bytes."""
    msg = email.message.EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = "Test message"
    msg["Message-ID"] = "<unique-id-001@example.com>"
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.set_content("Hello, this is a test email body.")
    return msg.as_bytes()


def _make_raw_email(uid: int) -> bytes:
    """Build a unique RFC822 email for a given uid."""
    msg = email.message.EmailMessage()
    msg["From"] = "sender@example.com"
    msg["To"] = "recipient@example.com"
    msg["Subject"] = f"Test message {uid}"
    msg["Message-ID"] = f"<unique-id-{uid:04d}@example.com>"
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg.set_content(f"Body for message {uid}.")
    return msg.as_bytes()


def _mock_imap_client(
    uids: list[int],
    fail_uid: int | None = None,
) -> AsyncMock:
    """Create a mock ImapClient with predefined UIDs and messages.

    Args:
        uids: UIDs the server "has".
        fail_uid: If set, fetching this UID raises an exception.
    """
    client = AsyncMock()
    client.fetch_uids = AsyncMock(return_value=uids)

    async def _fetch_message(_folder: str, uid: int) -> bytes:
        if uid == fail_uid:
            raise RuntimeError(f"Simulated fetch failure for UID {uid}")
        return _make_raw_email(uid)

    client.fetch_message = AsyncMock(side_effect=_fetch_message)

    async def _fetch_flags(_folder: str, uid: int) -> list[str]:
        if uid == fail_uid:
            raise RuntimeError(
                f"Simulated flag fetch failure for UID {uid}"
            )
        return ["\\Seen"]

    client.fetch_flags = AsyncMock(side_effect=_fetch_flags)
    return client


# ---------------------------------------------------------------------------
# MaildirManager tests
# ---------------------------------------------------------------------------


class TestMaildirManager:
    """Tests for the MaildirManager class."""

    def test_maildir_ensure_creates_dirs(
        self, maildir_path: Path
    ) -> None:
        """Verify cur/, new/, tmp/ are created."""
        mgr = MaildirManager(maildir_path)
        folder_path = mgr.ensure_maildir("myacct", "INBOX")

        assert (folder_path / "cur").is_dir()
        assert (folder_path / "new").is_dir()
        assert (folder_path / "tmp").is_dir()

    def test_maildir_save_and_read(
        self,
        maildir_path: Path,
        sample_raw_email: bytes,
    ) -> None:
        """Save a message and read it back; bytes must be identical."""
        mgr = MaildirManager(maildir_path)
        path = mgr.save_message(
            "myacct", "INBOX", 42, sample_raw_email, ["\\Seen"]
        )

        assert path.exists()
        assert path.parent.name == "cur"
        read_back = mgr.read_message(path)
        assert read_back == sample_raw_email

    def test_maildir_flag_encoding(
        self,
        maildir_path: Path,
        sample_raw_email: bytes,
    ) -> None:
        """Verify \\Seen -> S and \\Flagged -> F in the filename."""
        mgr = MaildirManager(maildir_path)
        path = mgr.save_message(
            "myacct",
            "INBOX",
            10,
            sample_raw_email,
            ["\\Seen", "\\Flagged"],
        )

        # Flags should be sorted: F before S
        assert path.name.endswith(":2,FS")

    def test_maildir_list_uids(
        self,
        maildir_path: Path,
        sample_raw_email: bytes,
    ) -> None:
        """Save 3 messages; list_uids returns all 3 UIDs."""
        mgr = MaildirManager(maildir_path)
        for uid in (10, 20, 30):
            mgr.save_message(
                "myacct", "INBOX", uid, sample_raw_email, []
            )

        uids = mgr.list_uids("myacct", "INBOX")
        assert uids == {10, 20, 30}

    def test_maildir_update_flags(
        self,
        maildir_path: Path,
        sample_raw_email: bytes,
    ) -> None:
        """Save with \\Seen, update to \\Seen+\\Flagged, verify filename."""
        mgr = MaildirManager(maildir_path)
        path = mgr.save_message(
            "myacct", "INBOX", 7, sample_raw_email, ["\\Seen"]
        )
        assert path.name.endswith(":2,S")

        new_path = mgr.update_flags(
            path, ["\\Seen", "\\Flagged"]
        )
        assert new_path.name.endswith(":2,FS")
        assert new_path.exists()
        assert not path.exists()  # old name gone


# ---------------------------------------------------------------------------
# SyncEngine tests
# ---------------------------------------------------------------------------


class TestSyncEngine:
    """Tests for the SyncEngine class."""

    @pytest.mark.asyncio
    async def test_full_sync_downloads_messages(
        self,
        maildir_path: Path,
        db: Database,
        sample_account: AccountConfig,
    ) -> None:
        """Mock IMAP with 3 UIDs; verify all 3 end up in the db."""
        uids = [101, 102, 103]
        mock_imap = _mock_imap_client(uids)
        mgr = MaildirManager(maildir_path)
        parser = EmailParser()

        engine = SyncEngine(
            mock_imap, db, mgr, parser, sample_account
        )
        await engine.full_sync("INBOX")

        # Verify all 3 messages in the database
        messages = await db.search_messages(
            folder="INBOX", limit=100
        )
        assert len(messages) == 3

        # Verify UIDs match
        db_uids = {m["uid"] for m in messages}
        assert db_uids == set(uids)

        # Verify Maildir has 3 files
        local_uids = mgr.list_uids("testacct", "INBOX")
        assert local_uids == set(uids)

    @pytest.mark.asyncio
    async def test_incremental_sync_only_new(
        self,
        maildir_path: Path,
        db: Database,
        sample_account: AccountConfig,
    ) -> None:
        """Seed db with UIDs 1-3, server has 1-5; only 4,5 downloaded."""
        mgr = MaildirManager(maildir_path)
        parser = EmailParser()

        # Seed: full sync with UIDs 1,2,3
        initial_imap = _mock_imap_client([1, 2, 3])
        engine = SyncEngine(
            initial_imap, db, mgr, parser, sample_account
        )
        await engine.full_sync("INBOX")

        initial_msgs = await db.search_messages(
            folder="INBOX", limit=100
        )
        assert len(initial_msgs) == 3

        # Incremental: server now reports UIDs 4,5 as new
        incr_imap = _mock_imap_client([4, 5])
        engine2 = SyncEngine(
            incr_imap, db, mgr, parser, sample_account
        )
        new_mp_ids = await engine2.incremental_sync("INBOX", 3)

        assert len(new_mp_ids) == 2

        all_msgs = await db.search_messages(
            folder="INBOX", limit=100
        )
        assert len(all_msgs) == 5

    @pytest.mark.asyncio
    async def test_sync_skips_failed_messages(
        self,
        maildir_path: Path,
        db: Database,
        sample_account: AccountConfig,
    ) -> None:
        """One UID fetch raises; the other two still sync."""
        uids = [201, 202, 203]
        mock_imap = _mock_imap_client(uids, fail_uid=202)
        mgr = MaildirManager(maildir_path)
        parser = EmailParser()

        engine = SyncEngine(
            mock_imap, db, mgr, parser, sample_account
        )
        await engine.full_sync("INBOX")

        # UID 202 failed, so only 2 should be in the db
        messages = await db.search_messages(
            folder="INBOX", limit=100
        )
        assert len(messages) == 2

        db_uids = {m["uid"] for m in messages}
        assert 202 not in db_uids
        assert 201 in db_uids
        assert 203 in db_uids
