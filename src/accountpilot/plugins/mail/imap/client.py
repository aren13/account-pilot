"""Async IMAP client wrapping aioimaplib."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from aioimaplib import IMAP4, IMAP4_SSL

from accountpilot.config import resolve_password
from accountpilot.plugins.mail.imap import (
    AuthenticationError,
    ConnectionError,  # noqa: A004
    ImapError,
)
from accountpilot.plugins.mail.providers import get_provider

if TYPE_CHECKING:
    from aioimaplib import IMAP4ClientProtocol

    from accountpilot.config import AccountConfig, SyncConfig
    from accountpilot.plugins.mail.providers import Provider

# Data dir is needed for OAuth token cache; set by AccountPilot on init.
_data_dir: str = ""

logger = logging.getLogger(__name__)

# Regex to extract folder name from LIST response line.
# Example: '(\\HasNoChildren) "/" "INBOX"'
_LIST_RE = re.compile(r'\(.*?\)\s+".*?"\s+"?([^"]+)"?$')


def _uid_set(uids: list[int]) -> str:
    """Format a list of UIDs into a comma-separated IMAP UID set."""
    return ",".join(str(u) for u in uids)


class ImapClient:
    """Async IMAP client with per-folder connections.

    Wraps :mod:`aioimaplib` to provide a high-level, folder-aware API
    with automatic reconnection and provider-specific folder aliases.

    Args:
        account: The account configuration (host, port, auth, etc.).
        sync_config: Global sync parameters (timeouts, backoff).
    """

    def __init__(
        self,
        account: AccountConfig,
        sync_config: SyncConfig,
    ) -> None:
        self._account = account
        self._sync = sync_config
        self._provider: Provider = get_provider(account.provider)
        self._connections: dict[str, IMAP4 | IMAP4_SSL] = {}

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    async def connect(self, folder: str = "INBOX") -> None:
        """Open a connection, authenticate, and SELECT *folder*.

        Args:
            folder: IMAP folder to select after login.

        Raises:
            AuthenticationError: If login is rejected by the server.
            ConnectionError: If the TCP/TLS connection fails.
        """
        imap_cfg = self._account.imap

        try:
            if imap_cfg.encryption == "tls":
                conn = IMAP4_SSL(
                    host=imap_cfg.host,
                    port=imap_cfg.port,
                )
            else:
                conn = IMAP4(
                    host=imap_cfg.host,
                    port=imap_cfg.port,
                )

            await conn.wait_hello_from_server()

            if imap_cfg.encryption == "starttls":
                await conn.starttls()

        except OSError as exc:
            raise ConnectionError(
                f"Cannot connect to {imap_cfg.host}:{imap_cfg.port}: {exc}"
            ) from exc

        try:
            if imap_cfg.auth.method == "oauth2":
                from accountpilot.oauth import get_access_token

                token = get_access_token(
                    imap_cfg.auth,
                    _data_dir,
                    self._account.name,
                    self._account.email,
                )
                response = await conn.xoauth2(
                    self._account.email, token
                )
            else:
                password = resolve_password(imap_cfg.auth)
                response = await conn.login(
                    self._account.email, password
                )

            if response.result != "OK":
                raise AuthenticationError(
                    f"Login failed for {self._account.email}: "
                    f"{response.lines}"
                )
        except AuthenticationError:
            raise
        except Exception as exc:
            raise AuthenticationError(
                f"Login failed for {self._account.email}: {exc}"
            ) from exc

        resolved = self._provider.folder_alias(folder)
        response = await conn.select(resolved)
        if response.result != "OK":
            raise ImapError(
                f"SELECT {resolved} failed: {response.lines}"
            )

        self._connections[folder] = conn
        logger.info(
            "Connected to %s — folder %s (%s)",
            imap_cfg.host,
            folder,
            resolved,
        )

    async def disconnect(self, folder: str | None = None) -> None:
        """Close one or all connections.

        Args:
            folder: Specific folder connection to close, or ``None``
                to close every open connection.
        """
        if folder is not None:
            conn = self._connections.pop(folder, None)
            if conn is not None:
                await self._safe_logout(conn, folder)
            return

        for name, conn in list(self._connections.items()):
            await self._safe_logout(conn, name)
        self._connections.clear()

    async def reconnect(self, folder: str) -> None:
        """Disconnect and reconnect to *folder* with exponential backoff.

        Retries until the connection succeeds or the maximum delay is
        reached (at which point it raises the last error).
        """
        await self.disconnect(folder)

        delay = self._sync.reconnect_base_delay
        while True:
            try:
                await self.connect(folder)
                return
            except (ConnectionError, ImapError) as exc:
                if delay >= self._sync.reconnect_max_delay:
                    raise
                logger.warning(
                    "Reconnect to %s failed, retrying in %ds: %s",
                    folder,
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, self._sync.reconnect_max_delay)

    async def ensure_connected(self, folder: str) -> None:
        """Verify the connection for *folder* is alive; reconnect if not."""
        conn = self._connections.get(folder)
        if conn is None or not _is_alive(conn):
            logger.debug("Connection for %s is stale, reconnecting", folder)
            await self.reconnect(folder)

    # ------------------------------------------------------------------
    # IMAP operations
    # ------------------------------------------------------------------

    async def list_folders(self) -> list[str]:
        """Return a list of all IMAP folder names on the server."""
        conn = await self._get_conn("INBOX")
        response = await conn.list("", "*")
        if response.result != "OK":
            raise ImapError(f"LIST failed: {response.lines}")

        folders: list[str] = []
        for line in response.lines:
            if not isinstance(line, str) or not line.strip():
                continue
            match = _LIST_RE.match(line)
            if match:
                folders.append(match.group(1))
        return folders

    async def fetch_uids(
        self,
        folder: str,
        since_uid: int | None = None,
    ) -> list[int]:
        """Fetch message UIDs in *folder*.

        Args:
            folder: IMAP folder name.
            since_uid: If given, only UIDs greater than this value.

        Returns:
            Sorted list of integer UIDs.
        """
        conn = await self._get_conn(folder)
        criteria = f"UID {since_uid + 1}:*" if since_uid else "ALL"
        response = await conn.uid_search(criteria)
        if response.result != "OK":
            raise ImapError(f"UID SEARCH failed: {response.lines}")

        uids: list[int] = []
        for line in response.lines:
            if isinstance(line, str):
                for token in line.split():
                    if token.isdigit():
                        uids.append(int(token))
        return sorted(uids)

    async def fetch_message(self, folder: str, uid: int) -> bytes:
        """Fetch the full RFC-822 message for *uid*.

        Args:
            folder: IMAP folder name.
            uid: Message UID.

        Returns:
            Raw message bytes.
        """
        return await self._fetch_part(folder, uid, "RFC822")

    async def fetch_headers(self, folder: str, uid: int) -> bytes:
        """Fetch only the RFC-822 headers for *uid*.

        Args:
            folder: IMAP folder name.
            uid: Message UID.

        Returns:
            Raw header bytes.
        """
        return await self._fetch_part(folder, uid, "RFC822.HEADER")

    async def fetch_flags(self, folder: str, uid: int) -> list[str]:
        """Fetch the current flags for *uid*.

        Args:
            folder: IMAP folder name.
            uid: Message UID.

        Returns:
            List of flag strings (e.g. ``['\\Seen', '\\Flagged']``).
        """
        conn = await self._get_conn(folder)
        response = await conn.uid("fetch", str(uid), "(FLAGS)")
        if response.result != "OK":
            raise ImapError(
                f"FETCH FLAGS failed for UID {uid}: {response.lines}"
            )
        flags: list[str] = []
        for line in response.lines:
            if isinstance(line, str):
                m = re.search(r"FLAGS\s*\(([^)]*)\)", line)
                if m:
                    flags = m.group(1).split()
                    break
        return flags

    async def set_flags(
        self,
        folder: str,
        uids: list[int],
        flags: list[str],
    ) -> None:
        """Add *flags* to the given UIDs.

        Args:
            folder: IMAP folder name.
            uids: List of message UIDs.
            flags: Flags to add (e.g. ``['\\Seen']``).
        """
        conn = await self._get_conn(folder)
        flag_str = " ".join(flags)
        response = await conn.uid(
            "store", _uid_set(uids), f"+FLAGS ({flag_str})"
        )
        if response.result != "OK":
            raise ImapError(
                f"STORE +FLAGS failed: {response.lines}"
            )

    async def remove_flags(
        self,
        folder: str,
        uids: list[int],
        flags: list[str],
    ) -> None:
        """Remove *flags* from the given UIDs.

        Args:
            folder: IMAP folder name.
            uids: List of message UIDs.
            flags: Flags to remove.
        """
        conn = await self._get_conn(folder)
        flag_str = " ".join(flags)
        response = await conn.uid(
            "store", _uid_set(uids), f"-FLAGS ({flag_str})"
        )
        if response.result != "OK":
            raise ImapError(
                f"STORE -FLAGS failed: {response.lines}"
            )

    async def move_messages(
        self,
        folder: str,
        uids: list[int],
        to_folder: str,
    ) -> None:
        """Move messages from *folder* to *to_folder*.

        Attempts the MOVE command first. If the server does not support
        it, falls back to COPY + flag ``\\Deleted`` + EXPUNGE.

        Args:
            folder: Source IMAP folder.
            uids: Message UIDs to move.
            to_folder: Destination IMAP folder.
        """
        conn = await self._get_conn(folder)
        dest = self._provider.folder_alias(to_folder)
        uid_set = _uid_set(uids)

        # Try MOVE first (RFC 6851).
        try:
            response = await conn.uid("move", uid_set, dest)
            if response.result == "OK":
                return
        except Exception:
            logger.debug("MOVE not supported, falling back to COPY+DELETE")

        # Fallback: COPY then mark deleted.
        await self.copy_messages(folder, uids, to_folder)
        await self.set_flags(folder, uids, ["\\Deleted"])
        await conn.expunge()

    async def copy_messages(
        self,
        folder: str,
        uids: list[int],
        to_folder: str,
    ) -> None:
        """Copy messages from *folder* to *to_folder*.

        Args:
            folder: Source IMAP folder.
            uids: Message UIDs to copy.
            to_folder: Destination IMAP folder.
        """
        conn = await self._get_conn(folder)
        dest = self._provider.folder_alias(to_folder)
        response = await conn.uid("copy", _uid_set(uids), dest)
        if response.result != "OK":
            raise ImapError(f"COPY failed: {response.lines}")

    async def delete_messages(
        self,
        folder: str,
        uids: list[int],
        *,
        permanent: bool = False,
    ) -> None:
        """Delete messages by UID.

        When *permanent* is ``True``, messages are flagged ``\\Deleted``
        and expunged immediately. Otherwise they are moved to the
        provider's trash folder.

        Args:
            folder: IMAP folder containing the messages.
            uids: Message UIDs to delete.
            permanent: Bypass trash and permanently expunge.
        """
        if permanent:
            await self.set_flags(folder, uids, ["\\Deleted"])
            conn = await self._get_conn(folder)
            await conn.expunge()
        else:
            trash = self._provider.trash_folder
            await self.move_messages(folder, uids, trash)

    async def append_message(
        self,
        folder: str,
        message: bytes,
        flags: list[str] | None = None,
    ) -> None:
        """Append a raw message to *folder*.

        Args:
            folder: Destination IMAP folder.
            message: Complete RFC-822 message bytes.
            flags: Optional flags to set on the appended message.
        """
        conn = await self._get_conn(folder)
        resolved = self._provider.folder_alias(folder)
        flag_str = f"({' '.join(flags)})" if flags else "()"
        response = await conn.append(
            resolved, flag_str, None, message
        )
        if response.result != "OK":
            raise ImapError(
                f"APPEND to {resolved} failed: {response.lines}"
            )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _get_conn(
        self, folder: str
    ) -> IMAP4 | IMAP4_SSL:
        """Return the connection for *folder*, ensuring it is alive."""
        await self.ensure_connected(folder)
        conn = self._connections.get(folder)
        if conn is None:
            raise ConnectionError(
                f"No connection available for folder {folder}"
            )
        return conn

    async def _fetch_part(
        self, folder: str, uid: int, part: str
    ) -> bytes:
        """Fetch a single message *part* by UID."""
        conn = await self._get_conn(folder)
        response = await conn.uid("fetch", str(uid), f"({part})")
        if response.result != "OK":
            raise ImapError(
                f"FETCH {part} failed for UID {uid}: {response.lines}"
            )
        for line in response.lines:
            if isinstance(line, bytes):
                return line
        raise ImapError(
            f"No data in FETCH {part} response for UID {uid}"
        )

    async def _safe_logout(
        self,
        conn: IMAP4 | IMAP4_SSL,
        folder: str,
    ) -> None:
        """Log out of *conn*, suppressing errors."""
        try:
            await conn.logout()
        except Exception:
            logger.debug(
                "Logout error for folder %s (ignored)", folder
            )

    @property
    def provider(self) -> Provider:
        """The Provider for this client.

        See :class:`~accountpilot.plugins.mail.providers.Provider`.
        """
        return self._provider


def _is_alive(conn: IMAP4 | IMAP4_SSL) -> bool:
    """Best-effort check whether *conn* still has an open transport."""
    protocol: IMAP4ClientProtocol | None = getattr(
        conn, "protocol", None
    )
    if protocol is None:
        return False
    transport = protocol.transport
    if transport is None:
        return False
    return not transport.is_closing()
