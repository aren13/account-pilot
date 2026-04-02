"""MailPilot async SQLite database layer with migrations."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Migration definitions
# ---------------------------------------------------------------------------

MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            display_name TEXT,
            provider TEXT DEFAULT 'custom',
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY,
            mp_id TEXT UNIQUE NOT NULL,
            account_id INTEGER REFERENCES accounts(id),
            message_id TEXT,
            uid INTEGER,
            folder TEXT,
            thread_id TEXT,
            from_address TEXT,
            from_name TEXT,
            to_addresses TEXT,
            cc_addresses TEXT,
            bcc_addresses TEXT,
            subject TEXT,
            date TIMESTAMP,
            in_reply_to TEXT,
            references_hdr TEXT,
            preview TEXT,
            has_attachments INTEGER DEFAULT 0,
            attachment_info TEXT,
            size_bytes INTEGER,
            flags TEXT DEFAULT '[]',
            maildir_path TEXT,
            xapian_docid INTEGER,
            is_deleted INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(account_id, uid, folder)
        );

        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS message_tags (
            message_id INTEGER REFERENCES messages(id),
            tag_id INTEGER REFERENCES tags(id),
            PRIMARY KEY (message_id, tag_id)
        );

        CREATE TABLE IF NOT EXISTS rule_log (
            id INTEGER PRIMARY KEY,
            rule_name TEXT,
            message_id INTEGER REFERENCES messages(id),
            actions TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY,
            account_id INTEGER REFERENCES accounts(id),
            to_addresses TEXT,
            subject TEXT,
            body_plain TEXT,
            body_html TEXT,
            status TEXT DEFAULT 'pending',
            error_message TEXT,
            retry_count INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            sent_at TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            event_type TEXT NOT NULL,
            message_id INTEGER,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_messages_mp_id ON messages(mp_id);
        CREATE INDEX IF NOT EXISTS idx_messages_message_id ON messages(message_id);
        CREATE INDEX IF NOT EXISTS idx_messages_thread_id ON messages(thread_id);
        CREATE INDEX IF NOT EXISTS idx_messages_account_folder
            ON messages(account_id, folder);
        CREATE INDEX IF NOT EXISTS idx_messages_date ON messages(date);
        CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
        CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at);
        CREATE INDEX IF NOT EXISTS idx_tags_name ON tags(name);
        """,
    ),
]


# ---------------------------------------------------------------------------
# Database class
# ---------------------------------------------------------------------------


class Database:
    """Async SQLite database wrapper for MailPilot."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    # -- Lifecycle -----------------------------------------------------------

    async def initialize(self) -> None:
        """Open connection, enable WAL + foreign keys, run pending migrations."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._run_migrations()
        logger.info("Database initialized at %s", self.db_path)

    async def close(self) -> None:
        """Close the database connection gracefully."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
            logger.info("Database connection closed")

    async def __aenter__(self) -> Database:
        await self.initialize()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.close()

    # -- Internal helpers ----------------------------------------------------

    @property
    def conn(self) -> aiosqlite.Connection:
        """Return the active connection or raise."""
        if self._conn is None:
            raise RuntimeError("Database not initialized — call initialize() first")
        return self._conn

    # -- Migrations ----------------------------------------------------------

    async def _run_migrations(self) -> None:
        """Create the schema_version table if needed, then apply pending migrations."""
        await self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER,
                applied_at TIMESTAMP
            )
            """
        )
        await self.conn.commit()

        cursor = await self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_version"
        )
        row = await cursor.fetchone()
        current_version: int = row[0]  # type: ignore[index]

        for version, sql in MIGRATIONS:
            if version <= current_version:
                continue
            logger.info("Applying migration %d", version)
            await self.conn.executescript(sql)
            await self.conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (version, datetime.now(UTC).isoformat()),
            )
            await self.conn.commit()
            logger.info("Migration %d applied", version)

    # -- mp_id generation ----------------------------------------------------

    async def _next_mp_id(self) -> str:
        """Generate the next ``mp-NNNNNN`` identifier."""
        cursor = await self.conn.execute("SELECT COALESCE(MAX(id), 0) FROM messages")
        row = await cursor.fetchone()
        next_id: int = row[0] + 1  # type: ignore[index]
        return f"mp-{next_id:06d}"

    # -- Account helpers -----------------------------------------------------

    async def insert_account(
        self,
        name: str,
        email: str,
        display_name: str | None = None,
        provider: str = "custom",
    ) -> int:
        """Insert a new account and return its id."""
        cursor = await self.conn.execute(
            """
            INSERT INTO accounts (name, email, display_name, provider)
            VALUES (?, ?, ?, ?)
            """,
            (name, email, display_name, provider),
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_account(self, name: str) -> dict | None:
        """Fetch an account by name."""
        cursor = await self.conn.execute(
            "SELECT * FROM accounts WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def get_account_by_id(self, account_id: int) -> dict | None:
        """Fetch an account by id."""
        cursor = await self.conn.execute(
            "SELECT * FROM accounts WHERE id = ?", (account_id,)
        )
        row = await cursor.fetchone()
        return dict(row) if row else None

    async def list_accounts(self) -> list[dict]:
        """Return all accounts."""
        cursor = await self.conn.execute("SELECT * FROM accounts")
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # -- Message helpers -----------------------------------------------------

    async def insert_message(self, **kwargs: Any) -> int:
        """Insert a message with auto-generated mp_id. Returns the new row id."""
        mp_id = await self._next_mp_id()
        kwargs["mp_id"] = mp_id

        # Serialize flags list to JSON string if present
        if "flags" in kwargs and isinstance(kwargs["flags"], list):
            kwargs["flags"] = json.dumps(kwargs["flags"])

        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        values = tuple(kwargs.values())

        cursor = await self.conn.execute(
            f"INSERT INTO messages ({columns}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_message(self, mp_id: str) -> dict | None:
        """Fetch a single message by mp_id."""
        cursor = await self.conn.execute(
            "SELECT * FROM messages WHERE mp_id = ?", (mp_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["flags"] = json.loads(result.get("flags") or "[]")
        return result

    async def get_message_by_message_id(self, message_id: str) -> dict | None:
        """Fetch a single message by its RFC message-id header."""
        cursor = await self.conn.execute(
            "SELECT * FROM messages WHERE message_id = ?", (message_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        result = dict(row)
        result["flags"] = json.loads(result.get("flags") or "[]")
        return result

    async def get_messages_by_thread(self, thread_id: str) -> list[dict]:
        """Return all messages in a thread, ordered by date."""
        cursor = await self.conn.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY date",
            (thread_id,),
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["flags"] = json.loads(d.get("flags") or "[]")
            results.append(d)
        return results

    async def update_message(self, mp_id: str, **kwargs: Any) -> None:
        """Update specified fields on a message (plus updated_at)."""
        if "flags" in kwargs and isinstance(kwargs["flags"], list):
            kwargs["flags"] = json.dumps(kwargs["flags"])

        kwargs["updated_at"] = datetime.now(UTC).isoformat()
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = tuple(kwargs.values()) + (mp_id,)

        await self.conn.execute(
            f"UPDATE messages SET {set_clause} WHERE mp_id = ?",  # noqa: S608
            values,
        )
        await self.conn.commit()

    async def delete_message(self, mp_id: str) -> None:
        """Soft-delete a message by setting is_deleted=1."""
        await self.conn.execute(
            "UPDATE messages SET is_deleted = 1, updated_at = ? WHERE mp_id = ?",
            (datetime.now(UTC).isoformat(), mp_id),
        )
        await self.conn.commit()

    async def search_messages(
        self,
        account_id: int | None = None,
        folder: str | None = None,
        is_deleted: bool = False,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict]:
        """Search messages with optional filters, ordered by date descending."""
        conditions: list[str] = ["is_deleted = ?"]
        params: list[Any] = [int(is_deleted)]

        if account_id is not None:
            conditions.append("account_id = ?")
            params.append(account_id)
        if folder is not None:
            conditions.append("folder = ?")
            params.append(folder)

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        cursor = await self.conn.execute(
            f"SELECT * FROM messages WHERE {where} ORDER BY date DESC LIMIT ? OFFSET ?",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["flags"] = json.loads(d.get("flags") or "[]")
            results.append(d)
        return results

    # -- Tag helpers ---------------------------------------------------------

    async def insert_tag(self, name: str) -> int:
        """Insert a new tag and return its id."""
        cursor = await self.conn.execute(
            "INSERT INTO tags (name) VALUES (?)", (name,)
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_or_create_tag(self, name: str) -> int:
        """Return the tag id, creating the tag if it does not exist."""
        cursor = await self.conn.execute(
            "SELECT id FROM tags WHERE name = ?", (name,)
        )
        row = await cursor.fetchone()
        if row:
            return row[0]  # type: ignore[index]
        return await self.insert_tag(name)

    async def add_message_tags(self, message_id: int, tag_names: list[str]) -> None:
        """Attach one or more tags to a message (by message row id)."""
        for name in tag_names:
            tag_id = await self.get_or_create_tag(name)
            await self.conn.execute(
                "INSERT OR IGNORE INTO message_tags (message_id, tag_id) VALUES (?, ?)",
                (message_id, tag_id),
            )
        await self.conn.commit()

    async def remove_message_tags(self, message_id: int, tag_names: list[str]) -> None:
        """Remove specified tags from a message."""
        for name in tag_names:
            cursor = await self.conn.execute(
                "SELECT id FROM tags WHERE name = ?", (name,)
            )
            row = await cursor.fetchone()
            if row:
                await self.conn.execute(
                    "DELETE FROM message_tags WHERE message_id = ? AND tag_id = ?",
                    (message_id, row[0]),
                )
        await self.conn.commit()

    async def get_message_tags(self, message_id: int) -> list[str]:
        """Return tag names for a given message row id."""
        cursor = await self.conn.execute(
            """
            SELECT t.name
            FROM tags t
            JOIN message_tags mt ON mt.tag_id = t.id
            WHERE mt.message_id = ?
            ORDER BY t.name
            """,
            (message_id,),
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

    async def list_tags(self) -> list[dict]:
        """Return all tags with their message counts."""
        cursor = await self.conn.execute(
            """
            SELECT t.id, t.name, t.created_at, COUNT(mt.message_id) AS message_count
            FROM tags t
            LEFT JOIN message_tags mt ON mt.tag_id = t.id
            GROUP BY t.id
            ORDER BY t.name
            """
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # -- Event helpers -------------------------------------------------------

    async def insert_event(
        self,
        account_id: int | None,
        event_type: str,
        message_id: int | None = None,
        details: str | None = None,
    ) -> int:
        """Log an event and return its id."""
        cursor = await self.conn.execute(
            """
            INSERT INTO events (account_id, event_type, message_id, details)
            VALUES (?, ?, ?, ?)
            """,
            (account_id, event_type, message_id, details),
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get_events(
        self,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Query events with optional filters."""
        conditions: list[str] = []
        params: list[Any] = []

        if event_type is not None:
            conditions.append("event_type = ?")
            params.append(event_type)
        if since is not None:
            conditions.append("created_at >= ?")
            params.append(since.strftime("%Y-%m-%d %H:%M:%S"))

        where = (" WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        cursor = await self.conn.execute(
            f"SELECT * FROM events{where} ORDER BY created_at DESC LIMIT ?",  # noqa: S608
            params,
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    # -- Outbox helpers ------------------------------------------------------

    async def insert_outbox(self, **kwargs: Any) -> int:
        """Insert an outbox entry and return its id."""
        columns = ", ".join(kwargs.keys())
        placeholders = ", ".join("?" for _ in kwargs)
        values = tuple(kwargs.values())

        cursor = await self.conn.execute(
            f"INSERT INTO outbox ({columns}) VALUES ({placeholders})",  # noqa: S608
            values,
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def update_outbox(self, outbox_id: int, **kwargs: Any) -> None:
        """Update specified fields on an outbox entry."""
        set_clause = ", ".join(f"{k} = ?" for k in kwargs)
        values = tuple(kwargs.values()) + (outbox_id,)

        await self.conn.execute(
            f"UPDATE outbox SET {set_clause} WHERE id = ?",  # noqa: S608
            values,
        )
        await self.conn.commit()

    async def get_pending_outbox(self) -> list[dict]:
        """Return all outbox entries with status 'pending'."""
        cursor = await self.conn.execute(
            "SELECT * FROM outbox WHERE status = 'pending' ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]
