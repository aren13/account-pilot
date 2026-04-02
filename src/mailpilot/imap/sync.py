"""Maildir storage manager and IMAP sync engine."""

from __future__ import annotations

import json
import logging
import shutil
import socket
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from mailpilot.config import AccountConfig
    from mailpilot.database import Database
    from mailpilot.imap.client import ImapClient
    from mailpilot.imap.parser import EmailParser

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Flag mapping: IMAP flag <-> Maildir single-char
# ---------------------------------------------------------------------------

_IMAP_TO_MAILDIR: dict[str, str] = {
    "\\Seen": "S",
    "\\Flagged": "F",
    "\\Answered": "R",
    "\\Draft": "D",
    "\\Deleted": "T",
}

_MAILDIR_TO_IMAP: dict[str, str] = {
    v: k for k, v in _IMAP_TO_MAILDIR.items()
}


# ---------------------------------------------------------------------------
# MaildirManager
# ---------------------------------------------------------------------------


class MaildirManager:
    """Manage Maildir-format storage for synced IMAP messages.

    Each account/folder combination gets a standard Maildir with
    ``cur/``, ``new/``, and ``tmp/`` subdirectories. Messages are
    written atomically (tmp -> cur) and named using the standard
    Maildir convention with UID embedded for easy lookup.
    """

    def __init__(self, base_path: Path) -> None:
        self._base = base_path

    # -- Public API ---------------------------------------------------------

    def ensure_maildir(self, account: str, folder: str) -> Path:
        """Create ``cur/``, ``new/``, ``tmp/`` under *account/folder*.

        Returns:
            The folder path (``base/account/folder``).
        """
        folder_path = self._base / account / folder
        for sub in ("cur", "new", "tmp"):
            (folder_path / sub).mkdir(parents=True, exist_ok=True)
        return folder_path

    def save_message(
        self,
        account: str,
        folder: str,
        uid: int,
        raw_bytes: bytes,
        flags: list[str],
    ) -> Path:
        """Write *raw_bytes* atomically to the Maildir.

        The message is first written to ``tmp/`` then moved to
        ``cur/`` with the appropriate flag suffix.

        Returns:
            Final path in ``cur/``.
        """
        folder_path = self.ensure_maildir(account, folder)
        flag_chars = self._imap_flags_to_maildir(flags)
        hostname = socket.gethostname()
        basename = f"{int(time.time())}.{uid}.{hostname}:2,{flag_chars}"

        tmp_path = folder_path / "tmp" / basename
        cur_path = folder_path / "cur" / basename

        tmp_path.write_bytes(raw_bytes)
        shutil.move(str(tmp_path), str(cur_path))

        return cur_path

    def get_message_path(
        self, account: str, folder: str, uid: int
    ) -> Path | None:
        """Find a message file by *uid* in ``cur/`` or ``new/``.

        Returns:
            The path if found, otherwise ``None``.
        """
        folder_path = self._base / account / folder
        uid_token = f".{uid}."
        for sub in ("cur", "new"):
            sub_path = folder_path / sub
            if not sub_path.is_dir():
                continue
            for entry in sub_path.iterdir():
                if uid_token in entry.name:
                    return entry
        return None

    def read_message(self, path: Path) -> bytes:
        """Read raw message bytes from *path*."""
        return path.read_bytes()

    def update_flags(self, path: Path, flags: list[str]) -> Path:
        """Rename *path* to reflect the new *flags*.

        Returns:
            The new path after renaming.
        """
        flag_chars = self._imap_flags_to_maildir(flags)
        name = path.name
        # Replace everything after ":2," with new flag chars
        base = (
            name[: name.index(":2,") + 3]
            if ":2," in name
            else name + ":2,"
        )
        new_name = base + flag_chars
        new_path = path.parent / new_name
        if new_path != path:
            path.rename(new_path)
        return new_path

    def delete_message(self, path: Path) -> None:
        """Remove the message file at *path*."""
        path.unlink(missing_ok=True)

    def list_uids(self, account: str, folder: str) -> set[int]:
        """Scan ``cur/`` and ``new/`` and extract UIDs from filenames.

        Returns:
            Set of integer UIDs found on disk.
        """
        folder_path = self._base / account / folder
        uids: set[int] = set()
        for sub in ("cur", "new"):
            sub_path = folder_path / sub
            if not sub_path.is_dir():
                continue
            for entry in sub_path.iterdir():
                uid = self._extract_uid(entry.name)
                if uid is not None:
                    uids.add(uid)
        return uids

    # -- Flag helpers -------------------------------------------------------

    @staticmethod
    def _imap_flags_to_maildir(flags: list[str]) -> str:
        """Convert IMAP flags to a sorted Maildir flag-char string."""
        chars: list[str] = []
        for flag in flags:
            ch = _IMAP_TO_MAILDIR.get(flag)
            if ch is not None:
                chars.append(ch)
        return "".join(sorted(chars))

    @staticmethod
    def _maildir_flags_to_imap(flag_chars: str) -> list[str]:
        """Convert Maildir flag chars back to IMAP flags."""
        flags: list[str] = []
        for ch in flag_chars:
            imap_flag = _MAILDIR_TO_IMAP.get(ch)
            if imap_flag is not None:
                flags.append(imap_flag)
        return flags

    # -- Internal -----------------------------------------------------------

    @staticmethod
    def _extract_uid(filename: str) -> int | None:
        """Extract the UID from a Maildir filename.

        Expected format: ``{timestamp}.{uid}.{hostname}:2,{flags}``
        """
        try:
            # Split on '.' — second element is the UID
            parts = filename.split(".")
            if len(parts) >= 3:
                return int(parts[1])
        except (ValueError, IndexError):
            pass
        return None


# ---------------------------------------------------------------------------
# SyncEngine
# ---------------------------------------------------------------------------


class SyncEngine:
    """Orchestrate IMAP-to-local synchronisation for a single account.

    Downloads messages into a :class:`MaildirManager`, parses them via
    :class:`~mailpilot.imap.parser.EmailParser`, and persists metadata
    in the :class:`~mailpilot.database.Database`.
    """

    def __init__(
        self,
        imap_client: ImapClient,
        db: Database,
        maildir: MaildirManager,
        parser: EmailParser,
        account: AccountConfig,
    ) -> None:
        self._imap = imap_client
        self._db = db
        self._maildir = maildir
        self._parser = parser
        self._account = account

    # -- Public sync methods ------------------------------------------------

    async def full_sync(
        self,
        folder: str,
        progress_callback: Callable | None = None,
    ) -> None:
        """Perform a full bi-directional sync for *folder*.

        Steps:
            1. Fetch all UIDs from the IMAP server.
            2. Get local UIDs from the Maildir.
            3. Download and store new messages (server-only).
            4. Mark locally-only messages as deleted in the database.
            5. Sync flags for messages present on both sides.
            6. Report progress via *progress_callback*.
        """
        account_name = self._account.name
        logger.info(
            "Starting full sync: account=%s folder=%s",
            account_name,
            folder,
        )

        # 1. Server UIDs
        server_uids = set(
            await self._imap.fetch_uids(folder)
        )

        # 2. Local UIDs
        local_uids = self._maildir.list_uids(account_name, folder)

        # 3. New on server — download
        new_uids = sorted(server_uids - local_uids)
        total = len(new_uids)
        for idx, uid in enumerate(new_uids, 1):
            await self._download_message(
                account_name, folder, uid
            )
            if progress_callback is not None:
                progress_callback(
                    "download", idx, total, folder
                )

        # 4. Deleted on server — mark locally
        deleted_uids = local_uids - server_uids
        await self._mark_deleted(
            account_name, folder, deleted_uids
        )

        # 5. Flag sync for existing
        existing_uids = server_uids & local_uids
        if existing_uids:
            await self._sync_flags_for_uids(
                account_name, folder, existing_uids
            )

        logger.info(
            "Full sync complete: account=%s folder=%s "
            "new=%d deleted=%d synced=%d",
            account_name,
            folder,
            len(new_uids),
            len(deleted_uids),
            len(existing_uids),
        )

    async def incremental_sync(
        self, folder: str, last_uid: int
    ) -> list[str]:
        """Download messages newer than *last_uid*.

        Returns:
            List of ``mp_id`` values for newly inserted messages.
        """
        account_name = self._account.name
        logger.info(
            "Incremental sync: account=%s folder=%s since_uid=%d",
            account_name,
            folder,
            last_uid,
        )

        new_uids = await self._imap.fetch_uids(
            folder, since_uid=last_uid
        )
        # Filter out the last_uid itself (IMAP UID ranges are inclusive)
        new_uids = [u for u in new_uids if u > last_uid]

        mp_ids: list[str] = []
        for uid in new_uids:
            mp_id = await self._download_message(
                account_name, folder, uid
            )
            if mp_id is not None:
                mp_ids.append(mp_id)

        logger.info(
            "Incremental sync complete: %d new messages",
            len(mp_ids),
        )
        return mp_ids

    async def sync_flags(self, folder: str) -> None:
        """Synchronise flags for all non-deleted messages in *folder*.

        Server flags win on conflict.
        """
        account_name = self._account.name
        account_row = await self._db.get_account(account_name)
        if account_row is None:
            logger.warning(
                "Account %s not found in db, skipping flag sync",
                account_name,
            )
            return
        account_id = account_row["id"]

        messages = await self._db.search_messages(
            account_id=account_id,
            folder=folder,
            is_deleted=False,
            limit=100_000,
        )

        for msg in messages:
            uid = msg["uid"]
            try:
                server_flags = await self._imap.fetch_flags(
                    folder, uid
                )
            except Exception:
                logger.warning(
                    "Failed to fetch flags for UID %d, skipping",
                    uid,
                    exc_info=True,
                )
                continue

            local_flags = msg["flags"]
            if isinstance(local_flags, str):
                local_flags = json.loads(local_flags)

            if sorted(server_flags) != sorted(local_flags):
                # Server wins
                await self._db.update_message(
                    msg["mp_id"], flags=server_flags
                )
                # Update maildir filename
                path = self._maildir.get_message_path(
                    account_name, folder, uid
                )
                if path is not None:
                    self._maildir.update_flags(path, server_flags)

                logger.debug(
                    "Flags updated for UID %d: %s -> %s",
                    uid,
                    local_flags,
                    server_flags,
                )

    async def sync_account(
        self,
        progress_callback: Callable | None = None,
    ) -> None:
        """Sync all configured folders for the account.

        Iterates over ``account.folders.sync`` and runs
        :meth:`full_sync` for each.
        """
        folders = self._account.folders.sync
        logger.info(
            "Syncing account %s — folders: %s",
            self._account.name,
            folders,
        )
        for folder in folders:
            try:
                await self.full_sync(
                    folder,
                    progress_callback=progress_callback,
                )
            except Exception:
                logger.exception(
                    "Failed to sync folder %s for account %s",
                    folder,
                    self._account.name,
                )

    # -- Private helpers ----------------------------------------------------

    async def _download_message(
        self,
        account_name: str,
        folder: str,
        uid: int,
    ) -> str | None:
        """Download, store, parse, and insert a single message.

        Returns:
            The ``mp_id`` of the inserted message, or ``None`` if
            the message was skipped (duplicate or error).
        """
        try:
            raw_bytes = await self._imap.fetch_message(folder, uid)
            flags = await self._imap.fetch_flags(folder, uid)
        except Exception:
            logger.warning(
                "Failed to fetch UID %d from %s/%s, skipping",
                uid,
                account_name,
                folder,
                exc_info=True,
            )
            return None

        # Parse headers/body
        parsed = self._parser.parse_message(raw_bytes)

        # Deduplication: skip if message_id already exists
        message_id = parsed.get("message_id", "")
        if message_id:
            existing = await self._db.get_message_by_message_id(
                message_id
            )
            if existing is not None:
                logger.debug(
                    "Duplicate message_id %s (UID %d), skipping",
                    message_id,
                    uid,
                )
                return None

        # Ensure account exists in db
        account_row = await self._db.get_account(account_name)
        if account_row is None:
            account_id = await self._db.insert_account(
                name=account_name,
                email=self._account.email,
                display_name=self._account.display_name,
                provider=self._account.provider,
            )
        else:
            account_id = account_row["id"]

        # Save to Maildir
        maildir_path = self._maildir.save_message(
            account_name, folder, uid, raw_bytes, flags
        )

        # Insert into database
        try:
            row_id = await self._db.insert_message(
                account_id=account_id,
                uid=uid,
                folder=folder,
                flags=flags,
                maildir_path=str(maildir_path),
                **parsed,
            )
        except Exception:
            logger.warning(
                "Failed to insert UID %d into db, skipping",
                uid,
                exc_info=True,
            )
            return None

        # Retrieve mp_id
        cursor = await self._db.conn.execute(
            "SELECT mp_id FROM messages WHERE id = ?", (row_id,)
        )
        row = await cursor.fetchone()
        mp_id: str = row[0]  # type: ignore[index]

        logger.debug(
            "Downloaded UID %d -> %s (%s)",
            uid,
            mp_id,
            parsed.get("subject", "(no subject)"),
        )
        return mp_id

    async def _mark_deleted(
        self,
        account_name: str,
        folder: str,
        uids: set[int],
    ) -> None:
        """Mark messages as deleted in the database."""
        if not uids:
            return

        account_row = await self._db.get_account(account_name)
        if account_row is None:
            return
        account_id = account_row["id"]

        for uid in uids:
            cursor = await self._db.conn.execute(
                "SELECT mp_id FROM messages "
                "WHERE account_id = ? AND uid = ? AND folder = ? "
                "AND is_deleted = 0",
                (account_id, uid, folder),
            )
            row = await cursor.fetchone()
            if row is not None:
                mp_id: str = row[0]  # type: ignore[index]
                await self._db.delete_message(mp_id)
                logger.debug(
                    "Marked UID %d (%s) as deleted", uid, mp_id
                )

    async def _sync_flags_for_uids(
        self,
        account_name: str,
        folder: str,
        uids: set[int],
    ) -> None:
        """Sync flags for a specific set of UIDs."""
        account_row = await self._db.get_account(account_name)
        if account_row is None:
            return
        account_id = account_row["id"]

        for uid in uids:
            try:
                server_flags = await self._imap.fetch_flags(
                    folder, uid
                )
            except Exception:
                logger.warning(
                    "Flag fetch failed for UID %d, skipping",
                    uid,
                    exc_info=True,
                )
                continue

            cursor = await self._db.conn.execute(
                "SELECT mp_id, flags FROM messages "
                "WHERE account_id = ? AND uid = ? AND folder = ? "
                "AND is_deleted = 0",
                (account_id, uid, folder),
            )
            row = await cursor.fetchone()
            if row is None:
                continue

            mp_id: str = row[0]  # type: ignore[index]
            local_flags_raw = row[1]  # type: ignore[index]
            local_flags = (
                json.loads(local_flags_raw)
                if isinstance(local_flags_raw, str)
                else local_flags_raw
            )

            if sorted(server_flags) != sorted(local_flags):
                await self._db.update_message(
                    mp_id, flags=server_flags
                )
                path = self._maildir.get_message_path(
                    account_name, folder, uid
                )
                if path is not None:
                    self._maildir.update_flags(path, server_flags)
