# AccountPilot AP-SP2 — iMessage Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second source plugin (`accountpilot.plugins.imessage`) that reads from the local `~/Library/Messages/chat.db`, persists messages through the SP0 Storage façade, and runs as a `chat.db`-watching daemon. After this slice, AccountPilot is genuinely multi-source: mail and iMessage flow into one DB through the same plugin contract.

**Architecture:** A new `IMessagePlugin` implements the 5-hook lifecycle. It composes a `ChatDbReader` (read-only sqlite3 on `~/Library/Messages/chat.db` with `?mode=ro` URI), an `AttachmentReader` (loads bytes from `~/Library/Messages/Attachments/...` files referenced in chat.db), and a `ChatDbWatcher` (`watchdog`-based file-watcher with debounce). Sender/participant handles are dispatched to `kind='phone'` or `kind='email'` based on shape so cross-source identity unification with mail correspondents works automatically — phone-shaped handles collide with phones already stored from Gmail, satisfying acceptance §7.3 #2.

**Tech Stack:** Python 3.11+ stdlib `sqlite3` (sync), `watchdog>=4.0` for file watching, Pydantic v2, Click, aiosqlite (write-side via Storage), pytest + pytest-asyncio. macOS-only (chat.db is Apple's). Plugin-loader uses the same `accountpilot.plugins` entry-point group as the mail plugin.

**Reference spec:** `docs/specs/2026-05-01-storage-rewrite-design.md` §7.3 — the five hardware acceptance criteria gate this slice.

---

## Pre-flight Notes

- **Working branch:** `main`. Same workflow as SP0/SP1.
- **Full Disk Access:** any process reading `~/Library/Messages/chat.db` (Python interpreter, daemon, test runner) needs FDA granted in System Settings → Privacy & Security → Full Disk Access. The hardware acceptance task documents this.
- **Test isolation:** all tests use a synthetic chat.db built in `tmp_path` with a minimal Apple-shaped schema. Real Apple chat.db is read only by the user's hardware-acceptance run, never by automated tests.
- **TDD discipline:** every new module gets a failing test first. Plugin and CLI follow SP1's patterns (FakeImap → FakeChatDbReader injection seam).
- **Cross-source identity (acceptance §7.3 #2):** instead of always storing iMessage handles as `kind='imessage_handle'`, we dispatch by shape — phone-like handles → `kind='phone'`, email-like → `kind='email'`, fallback → `kind='imessage_handle'`. Phones already in `identifiers` from Gmail correspondents naturally collide; `Storage.upsert_owner`'s auto-merge (added in SP1 Task 3) handles consolidation when the user later declares them as the same owner.
- **Schema migration:** none required. Existing tables (`messages`, `imessage_details`, `attachments`, `message_people`) cover everything iMessage needs. The iMessage chat.db ROWID isn't stored on our side; the watermark is `Storage.latest_sent_at(account_id)` (already exists from SP0 Task 12) — chat.db has a `date` column we filter on.
- **Date conversion:** Apple stores `message.date` as INT64 nanoseconds-since-2001-01-01-UTC. To Python datetime: `datetime(2001, 1, 1, tzinfo=UTC) + timedelta(microseconds=date / 1000)`. Helper lives in `reader.py`.
- **`message.text` may be NULL** when the body lives in the `attributedBody` BLOB (rich text, replies, link previews, attachments-only). For SP2 we record whatever `text` says; NULL → empty body. The GUID, sender, attachments, and metadata still land correctly. Decoding `attributedBody` is deferred to SP3 polish.

---

## File Structure

**Created:**

```
src/accountpilot/plugins/imessage/
  __init__.py
  config.py                       # IMessageAccountConfig, IMessagePluginConfig
  reader.py                       # ChatDbReader: open chat.db ro, query → IMessageMessage
  attachments.py                  # load attachment bytes from ~/Library/Messages/Attachments/
  watcher.py                      # ChatDbWatcher: watchdog observer + debounce
  plugin.py                       # IMessagePlugin (5 hooks)
  cli.py                          # accountpilot imessage {backfill,sync,daemon}

tests/accountpilot/plugins/imessage/
  __init__.py
  conftest.py                     # build_chatdb fixture: creates a minimal Apple-shaped chat.db
  test_config.py
  test_reader.py
  test_attachments.py
  test_watcher.py
  test_plugin.py
  test_cli.py

~/Projects/infra/configs/machines/ae/launchd/
  com.accountpilot.imessage.daemon.plist     # deploy artifact (manual bootstrap)
```

**Modified:**

```
pyproject.toml                    # add `watchdog` dep + register imessage entry point
docs/how-to/                      # add ap-sp2-acceptance-guide.md (Task 12)
CHANGELOG.md                      # AP-SP2 entry
ROADMAP.md                        # mark SP2 done
```

---

### Task 1: Pre-flight — pyproject changes

**Files:**
- Modify: `pyproject.toml`

Add the `watchdog` dependency for file-watching, register the `imessage` plugin entry point. Forward-only; the class doesn't exist until Task 7.

- [ ] **Step 1: Edit `pyproject.toml`**

In the `[project] dependencies = [...]` list, append:

```toml
    "watchdog>=4.0",
```

In the `[project.entry-points."accountpilot.plugins"]` section, add the second entry alongside `mail`:

```toml
[project.entry-points."accountpilot.plugins"]
mail = "accountpilot.plugins.mail.plugin:MailPlugin"
imessage = "accountpilot.plugins.imessage.plugin:IMessagePlugin"
```

- [ ] **Step 2: Reinstall + smoke**

```bash
pip install -e ".[dev]"
python -c "import watchdog; print(watchdog.__version__)"
```

Expected: a version string (4.x).

- [ ] **Step 3: Verify SP1 tests still pass**

```bash
pytest tests/accountpilot -q
```

Expected: 149 passed (or whatever SP1's final count was — should not decrease).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
chore: register imessage plugin + add watchdog dep

Add the accountpilot.plugins.imessage.plugin:IMessagePlugin entry point
(class lands in Task 7) and the watchdog>=4.0 dependency for the
chat.db file-watcher in Task 5.

mail plugin stays untouched. The discover_plugins() loop in cli.py
will register the imessage subgroup automatically once the package
ships its `imessage_group` Click group (Task 8).
EOF
)"
```

---

### Task 2: iMessage config models

**Files:**
- Create: `src/accountpilot/plugins/imessage/__init__.py`
- Create: `src/accountpilot/plugins/imessage/config.py`
- Create: `tests/accountpilot/plugins/imessage/__init__.py`
- Create: `tests/accountpilot/plugins/imessage/test_config.py`

`IMessageAccountConfig` and `IMessagePluginConfig` parse the `plugins.imessage` block of `config.yaml`. iMessage is single-account-per-machine in v1 (the local user's chat.db), so `accounts` typically has length 1.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/plugins/imessage/test_config.py`:

```python
from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from accountpilot.plugins.imessage.config import (
    IMessageAccountConfig,
    IMessagePluginConfig,
)


def test_account_minimum_fields() -> None:
    a = IMessageAccountConfig(
        identifier="+15551234567",
        owner="+15551234567",
    )
    assert a.identifier == "+15551234567"
    assert a.chat_db_path == Path.home() / "Library" / "Messages" / "chat.db"


def test_account_chat_db_path_override() -> None:
    a = IMessageAccountConfig(
        identifier="+15551234567",
        owner="+15551234567",
        chat_db_path=Path("/tmp/test-chat.db"),
    )
    assert a.chat_db_path == Path("/tmp/test-chat.db")


def test_account_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        IMessageAccountConfig(
            identifier="+15551234567",
            owner="+15551234567",
            something_unknown="oops",   # type: ignore[call-arg]
        )


def test_plugin_default_debounce_and_backfill_window() -> None:
    cfg = IMessagePluginConfig(accounts=[])
    assert cfg.debounce_seconds == 2.0
    assert cfg.backfill_chunk == 500
```

`tests/accountpilot/plugins/imessage/__init__.py`: empty.

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/imessage/test_config.py -v
```

Expected: ImportError on `accountpilot.plugins.imessage.config`.

- [ ] **Step 3: Implement**

`src/accountpilot/plugins/imessage/__init__.py`:

```python
"""AccountPilot iMessage plugin — chat.db reader + watchdog file-watcher."""
```

`src/accountpilot/plugins/imessage/config.py`:

```python
"""iMessage plugin config models.

The global config loader hands the `plugins.imessage` sub-tree to
IMessagePluginConfig.model_validate(...). iMessage is single-account-
per-machine in v1 (the local user's chat.db).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _default_chat_db_path() -> Path:
    return Path.home() / "Library" / "Messages" / "chat.db"


class IMessageAccountConfig(_StrictBase):
    identifier: str
    owner: str
    chat_db_path: Path = Field(default_factory=_default_chat_db_path)


class IMessagePluginConfig(_StrictBase):
    accounts: list[IMessageAccountConfig] = Field(default_factory=list)
    debounce_seconds: float = 2.0    # watcher debounce window
    backfill_chunk: int = 500        # rows per chat.db query batch
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/plugins/imessage/test_config.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/plugins/imessage tests/accountpilot/plugins/imessage
git commit -m "$(cat <<'EOF'
feat(plugins/imessage): config models

IMessageAccountConfig (identifier, owner, chat_db_path) +
IMessagePluginConfig (accounts list, debounce_seconds=2.0,
backfill_chunk=500). chat_db_path defaults to
~/Library/Messages/chat.db; tests can override.

extra='forbid' so unknown YAML keys fail loudly.
EOF
)"
```

---

### Task 3: ChatDbReader — synthetic chat.db fixture + read query

**Files:**
- Create: `src/accountpilot/plugins/imessage/reader.py`
- Create: `tests/accountpilot/plugins/imessage/conftest.py`
- Create: `tests/accountpilot/plugins/imessage/test_reader.py`

`ChatDbReader.read_messages(since_ns: int | None = None)` opens chat.db read-only via sqlite3 URI mode, joins `message` + `chat_message_join` + `chat` + `handle` to assemble per-message metadata, and yields `IMessageMessage` Pydantic models. The `since_ns` filter is `WHERE message.date > since_ns` — Apple-Cocoa nanoseconds-since-2001 form.

- [ ] **Step 1: Write the conftest fixture builder**

`tests/accountpilot/plugins/imessage/conftest.py`:

```python
"""Build a synthetic chat.db file with the minimal Apple-shaped schema.

Apple's real chat.db has dozens of tables and hundreds of columns; we
mirror only what ChatDbReader joins on. This keeps tests independent of
macOS Full Disk Access and runnable on any platform.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

# Apple's epoch is 2001-01-01 UTC; chat.db stores `date` as nanoseconds
# since that epoch.
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def to_apple_ns(dt: datetime) -> int:
    """Convert a tz-aware datetime to Apple-Cocoa nanoseconds-since-2001."""
    delta = dt - _APPLE_EPOCH
    return int(delta.total_seconds() * 1_000_000_000)


@pytest.fixture
def chatdb_path(tmp_path: Path) -> Path:
    """Return a path to a freshly-built synthetic chat.db file."""
    db_path = tmp_path / "chat.db"
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE handle (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            id TEXT NOT NULL,
            service TEXT NOT NULL DEFAULT 'iMessage'
        );
        CREATE TABLE chat (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            guid TEXT UNIQUE NOT NULL,
            chat_identifier TEXT,
            display_name TEXT
        );
        CREATE TABLE message (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            guid TEXT UNIQUE NOT NULL,
            text TEXT,
            handle_id INTEGER REFERENCES handle(ROWID),
            service TEXT,
            date INTEGER,
            date_read INTEGER,
            is_from_me INTEGER DEFAULT 0,
            is_read INTEGER DEFAULT 0,
            cache_has_attachments INTEGER DEFAULT 0
        );
        CREATE TABLE chat_message_join (
            chat_id INTEGER REFERENCES chat(ROWID),
            message_id INTEGER REFERENCES message(ROWID),
            PRIMARY KEY (chat_id, message_id)
        );
        CREATE TABLE chat_handle_join (
            chat_id INTEGER REFERENCES chat(ROWID),
            handle_id INTEGER REFERENCES handle(ROWID),
            PRIMARY KEY (chat_id, handle_id)
        );
        CREATE TABLE attachment (
            ROWID INTEGER PRIMARY KEY AUTOINCREMENT,
            guid TEXT UNIQUE NOT NULL,
            filename TEXT,
            mime_type TEXT,
            transfer_name TEXT
        );
        CREATE TABLE message_attachment_join (
            message_id INTEGER REFERENCES message(ROWID),
            attachment_id INTEGER REFERENCES attachment(ROWID),
            PRIMARY KEY (message_id, attachment_id)
        );
    """)
    conn.commit()
    conn.close()
    return db_path


def insert_handle(db: Path, *, identifier: str) -> int:
    """Insert a handle row, return its ROWID."""
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO handle (id, service) VALUES (?, 'iMessage')",
        (identifier,),
    )
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    assert rowid is not None
    return rowid


def insert_chat(db: Path, *, guid: str, identifier: str | None = None,
                display_name: str | None = None) -> int:
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO chat (guid, chat_identifier, display_name) VALUES (?, ?, ?)",
        (guid, identifier, display_name),
    )
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    assert rowid is not None
    return rowid


def insert_message(
    db: Path, *, guid: str, text: str | None, handle_rowid: int,
    chat_rowid: int, sent_at: datetime, is_from_me: bool = False,
    is_read: bool = True, service: str = "iMessage",
) -> int:
    """Insert a message and link it to a chat. Returns message ROWID."""
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO message "
        "(guid, text, handle_id, service, date, is_from_me, is_read) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (guid, text, handle_rowid, service,
         to_apple_ns(sent_at),
         1 if is_from_me else 0,
         1 if is_read else 0),
    )
    msg_rowid = cur.lastrowid
    conn.execute(
        "INSERT INTO chat_message_join (chat_id, message_id) VALUES (?, ?)",
        (chat_rowid, msg_rowid),
    )
    conn.commit()
    conn.close()
    assert msg_rowid is not None
    return msg_rowid


def add_chat_participant(db: Path, *, chat_rowid: int, handle_rowid: int) -> None:
    conn = sqlite3.connect(db)
    conn.execute(
        "INSERT INTO chat_handle_join (chat_id, handle_id) VALUES (?, ?)",
        (chat_rowid, handle_rowid),
    )
    conn.commit()
    conn.close()
```

- [ ] **Step 2: Write the failing reader test**

`tests/accountpilot/plugins/imessage/test_reader.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from accountpilot.plugins.imessage.reader import ChatDbReader
from tests.accountpilot.plugins.imessage.conftest import (
    add_chat_participant,
    insert_chat,
    insert_handle,
    insert_message,
    to_apple_ns,
)


def test_read_messages_yields_imessage_models(chatdb_path: Path) -> None:
    melis = insert_handle(chatdb_path, identifier="+905052490140")
    chat = insert_chat(chatdb_path, guid="iMessage;-;+905052490140",
                       identifier="+905052490140")
    add_chat_participant(chatdb_path, chat_rowid=chat, handle_rowid=melis)
    insert_message(
        chatdb_path, guid="GUID-1", text="hi from melis",
        handle_rowid=melis, chat_rowid=chat,
        sent_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        is_from_me=False,
    )

    reader = ChatDbReader(chatdb_path, account_id=1)
    messages = list(reader.read_messages())

    assert len(messages) == 1
    msg = messages[0]
    assert msg.account_id == 1
    assert msg.external_id == "GUID-1"
    assert msg.body_text == "hi from melis"
    assert msg.sender_handle == "+905052490140"
    assert msg.chat_guid == "iMessage;-;+905052490140"
    assert msg.direction == "inbound"
    assert msg.service == "iMessage"
    assert msg.is_read is True
    assert msg.sent_at == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


def test_read_messages_outbound_marker(chatdb_path: Path) -> None:
    me = insert_handle(chatdb_path, identifier="+15551234567")
    chat = insert_chat(chatdb_path, guid="iMessage;-;+15551234567")
    insert_message(
        chatdb_path, guid="GUID-OUT", text="reply",
        handle_rowid=me, chat_rowid=chat,
        sent_at=datetime(2026, 5, 1, 12, 5, tzinfo=UTC),
        is_from_me=True,
    )

    reader = ChatDbReader(chatdb_path, account_id=1)
    messages = list(reader.read_messages())

    assert messages[0].direction == "outbound"


def test_read_messages_since_filter(chatdb_path: Path) -> None:
    h = insert_handle(chatdb_path, identifier="+1")
    chat = insert_chat(chatdb_path, guid="c1")
    t1 = datetime(2026, 5, 1, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 5, 1, 11, 0, tzinfo=UTC)
    t3 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    insert_message(chatdb_path, guid="m1", text="a", handle_rowid=h,
                   chat_rowid=chat, sent_at=t1)
    insert_message(chatdb_path, guid="m2", text="b", handle_rowid=h,
                   chat_rowid=chat, sent_at=t2)
    insert_message(chatdb_path, guid="m3", text="c", handle_rowid=h,
                   chat_rowid=chat, sent_at=t3)

    reader = ChatDbReader(chatdb_path, account_id=1)
    msgs = list(reader.read_messages(since_ns=to_apple_ns(t1)))

    # since_ns=t1 means strict >, so m2 and m3 only.
    guids = {m.external_id for m in msgs}
    assert guids == {"m2", "m3"}


def test_read_messages_group_chat_lists_participants(
    chatdb_path: Path,
) -> None:
    a = insert_handle(chatdb_path, identifier="+1")
    b = insert_handle(chatdb_path, identifier="+2")
    c = insert_handle(chatdb_path, identifier="+3")
    chat = insert_chat(chatdb_path, guid="iMessage;+;chat-grp")
    add_chat_participant(chatdb_path, chat_rowid=chat, handle_rowid=a)
    add_chat_participant(chatdb_path, chat_rowid=chat, handle_rowid=b)
    add_chat_participant(chatdb_path, chat_rowid=chat, handle_rowid=c)
    insert_message(chatdb_path, guid="grp-1", text="hello group",
                   handle_rowid=a, chat_rowid=chat,
                   sent_at=datetime(2026, 5, 1, tzinfo=UTC))

    reader = ChatDbReader(chatdb_path, account_id=1)
    msg = list(reader.read_messages())[0]

    assert sorted(msg.participants) == ["+1", "+2", "+3"]


def test_read_messages_null_text_yields_empty_body(chatdb_path: Path) -> None:
    """When chat.db's text is NULL (rich-content message), body_text is empty
    rather than the literal string 'None'."""
    h = insert_handle(chatdb_path, identifier="+1")
    chat = insert_chat(chatdb_path, guid="c")
    insert_message(chatdb_path, guid="m1", text=None, handle_rowid=h,
                   chat_rowid=chat,
                   sent_at=datetime(2026, 5, 1, tzinfo=UTC))

    reader = ChatDbReader(chatdb_path, account_id=1)
    msg = list(reader.read_messages())[0]

    assert msg.body_text == ""
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/imessage/test_reader.py -v
```

Expected: ImportError on `accountpilot.plugins.imessage.reader`.

- [ ] **Step 4: Implement `src/accountpilot/plugins/imessage/reader.py`**

```python
"""ChatDbReader — read-only sqlite query over Apple's chat.db."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

from accountpilot.core.models import IMessageMessage

# Apple's epoch is 2001-01-01 UTC; chat.db `message.date` is nanoseconds
# since that epoch.
_APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)


def _apple_ns_to_datetime(ns: int) -> datetime:
    """Convert Apple-Cocoa nanoseconds-since-2001 → tz-aware UTC datetime."""
    return _APPLE_EPOCH + timedelta(microseconds=ns / 1000)


class ChatDbReader:
    """Read messages from a local Apple chat.db file.

    Opens the database read-only via the sqlite3 URI mode (`?mode=ro`) so
    a missing FDA grant fails fast with a clear error and never mutates
    Apple's file.
    """

    def __init__(self, chat_db_path: Path, account_id: int) -> None:
        self.chat_db_path = chat_db_path
        self.account_id = account_id

    def read_messages(
        self, *, since_ns: int | None = None
    ) -> Iterator[IMessageMessage]:
        """Yield IMessageMessage rows newer than `since_ns` (Apple ns).

        If `since_ns` is None, yields everything.
        """
        uri = f"file:{self.chat_db_path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            yield from self._iter_rows(conn, since_ns)
        finally:
            conn.close()

    def _iter_rows(
        self, conn: sqlite3.Connection, since_ns: int | None
    ) -> Iterator[IMessageMessage]:
        # One row per message. Joined to chat (for chat_guid) and handle
        # (for sender_handle). NULL handle (system messages) skipped.
        sql = """
            SELECT
                m.ROWID                AS msg_rowid,
                m.guid                 AS guid,
                COALESCE(m.text, '')   AS body,
                m.is_from_me           AS is_from_me,
                COALESCE(m.is_read, 0) AS is_read,
                m.date                 AS date_ns,
                m.date_read            AS date_read_ns,
                m.service              AS service,
                h.id                   AS sender_handle,
                c.guid                 AS chat_guid
            FROM message m
            LEFT JOIN handle h ON h.ROWID = m.handle_id
            JOIN chat_message_join cmj ON cmj.message_id = m.ROWID
            JOIN chat c ON c.ROWID = cmj.chat_id
            WHERE h.id IS NOT NULL
        """
        params: tuple[int, ...] = ()
        if since_ns is not None:
            sql += " AND m.date > ?"
            params = (since_ns,)
        sql += " ORDER BY m.date ASC, m.ROWID ASC"

        for row in conn.execute(sql, params):
            participants = [
                p["id"]
                for p in conn.execute(
                    "SELECT h.id FROM chat_handle_join chj "
                    "JOIN handle h ON h.ROWID = chj.handle_id "
                    "WHERE chj.chat_id = (SELECT ROWID FROM chat WHERE guid=?)",
                    (row["chat_guid"],),
                )
            ]
            sent_at = _apple_ns_to_datetime(row["date_ns"])
            date_read = (
                _apple_ns_to_datetime(row["date_read_ns"])
                if row["date_read_ns"]
                else None
            )
            service = (
                "iMessage"
                if (row["service"] or "iMessage") in {"iMessage", "RCS"}
                else "SMS"
            )
            yield IMessageMessage(
                account_id=self.account_id,
                external_id=str(row["guid"]),
                sent_at=sent_at,
                direction="outbound" if row["is_from_me"] else "inbound",
                sender_handle=str(row["sender_handle"]),
                chat_guid=str(row["chat_guid"]),
                participants=participants,
                body_text=str(row["body"] or ""),
                service=service,
                is_read=bool(row["is_read"]),
                date_read=date_read,
                attachments=[],   # populated by AttachmentReader in Task 4
            )
```

- [ ] **Step 5: Run tests pass**

```bash
pytest tests/accountpilot/plugins/imessage/test_reader.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add src/accountpilot/plugins/imessage/reader.py tests/accountpilot/plugins/imessage/conftest.py tests/accountpilot/plugins/imessage/test_reader.py
git commit -m "$(cat <<'EOF'
feat(plugins/imessage): chat.db reader

ChatDbReader opens Apple's chat.db read-only via sqlite3's URI mode
(?mode=ro) and yields IMessageMessage rows joined across message +
chat + handle + chat_message_join + chat_handle_join. NULL handle_id
(system events) is filtered out. NULL text is normalised to empty
string (rich-content messages whose body lives in attributedBody BLOB
are deferred to SP3 polish).

since_ns filter uses chat.db's nanoseconds-since-2001 form so the
plugin can resume from `Storage.latest_sent_at` (converted to Apple ns)
without any extra schema columns.

Tests use a synthetic chat.db built in tmp_path with the minimal
Apple-shaped schema. Real chat.db is exercised only by the hardware
acceptance task on AE.
EOF
)"
```

---

### Task 4: AttachmentReader — load attachment bytes from disk

**Files:**
- Create: `src/accountpilot/plugins/imessage/attachments.py`
- Modify: `tests/accountpilot/plugins/imessage/conftest.py` (add attachment helpers)
- Create: `tests/accountpilot/plugins/imessage/test_attachments.py`

chat.db's `attachment.filename` is an absolute path (or `~/Library/Messages/Attachments/...`). The plugin needs to read those bytes and bundle them as `AttachmentBlob`s on the `IMessageMessage`.

- [ ] **Step 1: Extend conftest with attachment helpers**

Append to `tests/accountpilot/plugins/imessage/conftest.py`:

```python
def insert_attachment(
    db: Path, *, message_rowid: int, guid: str, filename: str | None,
    mime_type: str | None = None, transfer_name: str | None = None,
) -> int:
    conn = sqlite3.connect(db)
    cur = conn.execute(
        "INSERT INTO attachment (guid, filename, mime_type, transfer_name) "
        "VALUES (?, ?, ?, ?)",
        (guid, filename, mime_type, transfer_name),
    )
    att_rowid = cur.lastrowid
    conn.execute(
        "INSERT INTO message_attachment_join (message_id, attachment_id) "
        "VALUES (?, ?)",
        (message_rowid, att_rowid),
    )
    conn.commit()
    conn.close()
    assert att_rowid is not None
    return att_rowid
```

- [ ] **Step 2: Write the failing attachment-reader test**

`tests/accountpilot/plugins/imessage/test_attachments.py`:

```python
from __future__ import annotations

import sqlite3
from pathlib import Path

from accountpilot.plugins.imessage.attachments import (
    AttachmentReader,
    load_attachments_for_message,
)
from tests.accountpilot.plugins.imessage.conftest import (
    insert_attachment,
    insert_chat,
    insert_handle,
    insert_message,
)


def _seed_attachment_file(tmp_path: Path) -> Path:
    p = tmp_path / "Attachments" / "ab" / "01" / "pic.jpg"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"\xff\xd8\xffSAMPLE")
    return p


def test_load_attachments_reads_bytes(
    chatdb_path: Path, tmp_path: Path
) -> None:
    h = insert_handle(chatdb_path, identifier="+1")
    chat = insert_chat(chatdb_path, guid="c1")
    from datetime import UTC, datetime
    msg_rowid = insert_message(
        chatdb_path, guid="m-att-1", text="see pic",
        handle_rowid=h, chat_rowid=chat,
        sent_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    att_path = _seed_attachment_file(tmp_path)
    insert_attachment(
        chatdb_path, message_rowid=msg_rowid,
        guid="att-1", filename=str(att_path), mime_type="image/jpeg",
        transfer_name="pic.jpg",
    )

    conn = sqlite3.connect(f"file:{chatdb_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        blobs = load_attachments_for_message(conn, msg_rowid)
    finally:
        conn.close()

    assert len(blobs) == 1
    assert blobs[0].filename == "pic.jpg"
    assert blobs[0].mime_type == "image/jpeg"
    assert blobs[0].content == b"\xff\xd8\xffSAMPLE"


def test_load_attachments_skips_missing_file(
    chatdb_path: Path, tmp_path: Path
) -> None:
    """If an attachment row references a path that no longer exists on
    disk, the loader skips it rather than raising. macOS sometimes
    purges old attachments while leaving chat.db rows behind."""
    h = insert_handle(chatdb_path, identifier="+1")
    chat = insert_chat(chatdb_path, guid="c1")
    from datetime import UTC, datetime
    msg_rowid = insert_message(
        chatdb_path, guid="m-att-2", text="missing",
        handle_rowid=h, chat_rowid=chat,
        sent_at=datetime(2026, 5, 1, tzinfo=UTC),
    )
    insert_attachment(
        chatdb_path, message_rowid=msg_rowid,
        guid="att-missing",
        filename=str(tmp_path / "ghost.bin"),  # never created
        mime_type="application/octet-stream",
    )

    conn = sqlite3.connect(f"file:{chatdb_path}?mode=ro", uri=True)
    try:
        blobs = load_attachments_for_message(conn, msg_rowid)
    finally:
        conn.close()

    assert blobs == []


def test_attachment_reader_expands_tilde(tmp_path: Path) -> None:
    """chat.db sometimes stores `~/Library/...` paths verbatim. The
    reader expands `~` before reading."""
    home_attachments = tmp_path / "fake-home" / "Library" / "Messages" / "Attachments"
    home_attachments.mkdir(parents=True)
    f = home_attachments / "x.txt"
    f.write_bytes(b"data")

    reader = AttachmentReader(home=tmp_path / "fake-home")
    assert reader.read("~/Library/Messages/Attachments/x.txt") == b"data"
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/imessage/test_attachments.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `src/accountpilot/plugins/imessage/attachments.py`**

```python
"""Load attachment bytes referenced by chat.db rows."""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from accountpilot.core.models import AttachmentBlob

log = logging.getLogger(__name__)


class AttachmentReader:
    """Read attachment bytes from disk, with `~` expansion against `home`.

    chat.db sometimes stores attachment paths as `~/Library/...` and
    sometimes as absolute `/Users/<name>/Library/...`. The reader
    handles both.
    """

    def __init__(self, home: Path | None = None) -> None:
        self.home = home if home is not None else Path.home()

    def _resolve(self, raw_path: str) -> Path:
        if raw_path.startswith("~"):
            return self.home / raw_path.lstrip("~/")
        return Path(raw_path)

    def read(self, raw_path: str) -> bytes:
        """Read bytes from `raw_path` (may start with `~`)."""
        return self._resolve(raw_path).read_bytes()


def load_attachments_for_message(
    conn: sqlite3.Connection,
    message_rowid: int,
    reader: AttachmentReader | None = None,
) -> list[AttachmentBlob]:
    """Return AttachmentBlob list for `message_rowid` from an open chat.db.

    Missing files (chat.db row references a path that no longer exists,
    common after macOS prunes old attachments) are skipped with a debug
    log line — they don't fail the whole save_imessage call.
    """
    rdr = reader or AttachmentReader()
    blobs: list[AttachmentBlob] = []
    rows = conn.execute(
        "SELECT a.filename, a.mime_type, a.transfer_name "
        "FROM attachment a "
        "JOIN message_attachment_join maj ON maj.attachment_id = a.ROWID "
        "WHERE maj.message_id = ?",
        (message_rowid,),
    )
    for row in rows:
        raw_path = row["filename"]
        if not raw_path:
            continue
        try:
            content = rdr.read(raw_path)
        except (FileNotFoundError, IsADirectoryError, PermissionError) as exc:
            log.debug("attachment %r missing/unreadable: %s", raw_path, exc)
            continue
        filename = (
            row["transfer_name"]
            or Path(raw_path).name
            or "attachment.bin"
        )
        blobs.append(AttachmentBlob(
            filename=filename,
            content=content,
            mime_type=row["mime_type"],
        ))
    return blobs
```

- [ ] **Step 5: Hook attachments into `ChatDbReader`**

Modify `src/accountpilot/plugins/imessage/reader.py`. At the top, import:

```python
from accountpilot.plugins.imessage.attachments import (
    AttachmentReader,
    load_attachments_for_message,
)
```

Update the `ChatDbReader.__init__` to accept an optional `AttachmentReader`:

```python
    def __init__(
        self,
        chat_db_path: Path,
        account_id: int,
        attachment_reader: AttachmentReader | None = None,
    ) -> None:
        self.chat_db_path = chat_db_path
        self.account_id = account_id
        self.attachment_reader = attachment_reader or AttachmentReader()
```

In `_iter_rows`, replace `attachments=[]` with:

```python
                attachments=load_attachments_for_message(
                    conn, row["msg_rowid"], self.attachment_reader,
                ),
```

- [ ] **Step 6: Run tests pass**

```bash
pytest tests/accountpilot/plugins/imessage -v
```

Expected: all green (4 config + 5 reader + 3 attachment tests).

- [ ] **Step 7: Commit**

```bash
git add src/accountpilot/plugins/imessage/attachments.py src/accountpilot/plugins/imessage/reader.py tests/accountpilot/plugins/imessage/conftest.py tests/accountpilot/plugins/imessage/test_attachments.py
git commit -m "$(cat <<'EOF'
feat(plugins/imessage): attachment reader + integration into ChatDbReader

AttachmentReader resolves attachment paths from chat.db (handles both
~/Library/... and absolute forms) and reads bytes. Missing-on-disk
attachments are skipped with a debug log — macOS prunes old
attachments while leaving the chat.db rows.

ChatDbReader now bundles AttachmentBlobs onto each IMessageMessage it
yields. transfer_name is preferred for the filename (it's the
human-readable original); falls back to the path basename or
'attachment.bin'.
EOF
)"
```

---

### Task 5: ChatDbWatcher — watchdog observer with debounce

**Files:**
- Create: `src/accountpilot/plugins/imessage/watcher.py`
- Create: `tests/accountpilot/plugins/imessage/test_watcher.py`

`ChatDbWatcher` wraps `watchdog.observers.Observer` watching the directory holding chat.db. On any modification event for the chat.db file, it debounces (collapses bursts within `debounce_seconds` into one notification) and calls a user-supplied callback.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/plugins/imessage/test_watcher.py`:

```python
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

from accountpilot.plugins.imessage.watcher import ChatDbWatcher


@pytest.mark.asyncio
async def test_watcher_fires_on_chat_db_modification(tmp_path: Path) -> None:
    chat_db = tmp_path / "chat.db"
    chat_db.write_bytes(b"")

    fired = asyncio.Event()
    fire_count = 0
    loop = asyncio.get_running_loop()

    def on_change() -> None:
        nonlocal fire_count
        fire_count += 1
        loop.call_soon_threadsafe(fired.set)

    watcher = ChatDbWatcher(chat_db, on_change=on_change, debounce_seconds=0.1)
    watcher.start()
    try:
        # Modify in a separate thread to avoid blocking on the watcher.
        def _touch() -> None:
            chat_db.write_bytes(b"changed")
        threading.Timer(0.05, _touch).start()
        await asyncio.wait_for(fired.wait(), timeout=2.0)
    finally:
        watcher.stop()

    assert fire_count >= 1


@pytest.mark.asyncio
async def test_watcher_debounces_rapid_modifications(tmp_path: Path) -> None:
    chat_db = tmp_path / "chat.db"
    chat_db.write_bytes(b"")

    fired = threading.Event()
    fire_count = 0

    def on_change() -> None:
        nonlocal fire_count
        fire_count += 1
        fired.set()

    watcher = ChatDbWatcher(chat_db, on_change=on_change, debounce_seconds=0.3)
    watcher.start()
    try:
        # 5 rapid writes inside the debounce window → at most 1-2 fires.
        for i in range(5):
            chat_db.write_bytes(f"v{i}".encode())
            await asyncio.sleep(0.02)
        # Wait past the debounce window for any trailing fire.
        await asyncio.sleep(0.5)
    finally:
        watcher.stop()

    # We accept 1 OR 2 fires (depends on whether the burst started a new
    # debounce window mid-flight). The point is "many fewer than 5".
    assert 1 <= fire_count <= 2
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/imessage/test_watcher.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement `src/accountpilot/plugins/imessage/watcher.py`**

```python
"""Watch chat.db for modifications, with debounce."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from pathlib import Path

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

log = logging.getLogger(__name__)


class _DebouncedChatDbHandler(FileSystemEventHandler):
    """Fires `on_change` no more than once per `debounce_seconds`."""

    def __init__(
        self,
        target_path: Path,
        on_change: Callable[[], None],
        debounce_seconds: float,
    ) -> None:
        self._target = target_path.resolve()
        self._on_change = on_change
        self._debounce = debounce_seconds
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def _fire(self) -> None:
        try:
            self._on_change()
        except Exception:  # noqa: BLE001
            log.exception("chat.db on_change callback raised")

    def _schedule(self) -> None:
        with self._lock:
            if self._timer is not None and self._timer.is_alive():
                return  # already scheduled — collapse this event
            self._timer = threading.Timer(self._debounce, self._fire)
            self._timer.daemon = True
            self._timer.start()

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        # chat.db's directory may also see writes to chat.db-wal /
        # chat.db-shm (SQLite WAL files). Treat those as relevant too.
        path = Path(str(event.src_path)).resolve()
        if path.name in {self._target.name,
                         self._target.name + "-wal",
                         self._target.name + "-shm"}:
            self._schedule()

    on_created = on_modified  # WAL files may be (re)created mid-write


class ChatDbWatcher:
    """File-watcher around `chat_db_path` with debounced `on_change`."""

    def __init__(
        self,
        chat_db_path: Path,
        on_change: Callable[[], None],
        debounce_seconds: float = 2.0,
    ) -> None:
        self._chat_db = chat_db_path.resolve()
        self._handler = _DebouncedChatDbHandler(
            self._chat_db, on_change, debounce_seconds,
        )
        self._observer: Observer | None = None

    def start(self) -> None:
        if self._observer is not None:
            return
        obs = Observer()
        obs.schedule(self._handler, str(self._chat_db.parent), recursive=False)
        obs.start()
        self._observer = obs
        log.info("chat.db watcher started on %s", self._chat_db)

    def stop(self) -> None:
        if self._observer is None:
            return
        self._observer.stop()
        self._observer.join(timeout=2.0)
        self._observer = None
        log.info("chat.db watcher stopped")
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/plugins/imessage/test_watcher.py -v
```

Expected: 2 passed.

If the second test (debounce) is flaky in CI (timer scheduling can vary), bump the sleeps slightly. Local dev should pass reliably.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/plugins/imessage/watcher.py tests/accountpilot/plugins/imessage/test_watcher.py
git commit -m "$(cat <<'EOF'
feat(plugins/imessage): chat.db file watcher with debounce

ChatDbWatcher wraps watchdog.Observer on the directory containing
chat.db (Apple uses SQLite WAL so writes also touch chat.db-wal /
chat.db-shm; the handler treats all three names as relevant).

A trailing-edge debounce (default 2s) collapses rapid bursts —
one Messages.app-driven sync usually emits dozens of WAL writes in
quick succession; we want one downstream sync_once per burst.

Tests use a synthetic chat.db file in tmp_path; no FDA needed.
EOF
)"
```

---

### Task 6: Cross-source identity — handle-kind dispatch helper

**Files:**
- Modify: `src/accountpilot/core/identity.py` (add `kind_for_imessage_handle`)
- Modify: `tests/accountpilot/unit/core/test_identity_normalize.py`

For acceptance §7.3 #2: phone-shaped iMessage handles should resolve to `kind='phone'` so they collide with phones already in `identifiers` from a Gmail correspondent. Email-shaped handles → `kind='email'`. Otherwise → `kind='imessage_handle'`.

This is a pure function in `core/identity.py`; the IMessagePlugin (Task 7) calls it before invoking `find_or_create_person`.

- [ ] **Step 1: Write the failing test**

Append to `tests/accountpilot/unit/core/test_identity_normalize.py`:

```python
from accountpilot.core.identity import kind_for_imessage_handle


@pytest.mark.parametrize(
    "raw, expected_kind",
    [
        ("+15551234567", "phone"),
        ("+90 505 249 01 39", "phone"),
        ("foo@example.com", "email"),
        ("Foo@Example.COM", "email"),
        ("some-arbitrary-handle", "imessage_handle"),
        ("12345", "imessage_handle"),  # bare digits without + → unknown
    ],
)
def test_kind_for_imessage_handle(raw: str, expected_kind: str) -> None:
    assert kind_for_imessage_handle(raw) == expected_kind
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/unit/core/test_identity_normalize.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

Append to `src/accountpilot/core/identity.py`:

```python
def kind_for_imessage_handle(raw: str) -> str:
    """Dispatch an iMessage handle to the right `identifiers.kind`.

    Cross-source identity (acceptance AP-SP2 §7.3 #2): a phone-shaped
    iMessage handle should collide with phones already stored from a
    Gmail correspondent so they resolve to the same `people` row. Same
    for email-shaped handles. Anything that doesn't match a known shape
    falls back to 'imessage_handle' (an Apple Account / Game Center
    handle, for example).
    """
    s = raw.strip()
    if "@" in s:
        return "email"
    if s.startswith("+"):
        normalized = normalize_phone(s)
        if normalized.startswith("+"):
            return "phone"
    return "imessage_handle"
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/unit/core/test_identity_normalize.py -v
```

Expected: all parametrize cases pass.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/identity.py tests/accountpilot/unit/core/test_identity_normalize.py
git commit -m "$(cat <<'EOF'
feat(core/identity): add kind_for_imessage_handle dispatch helper

Per AP-SP2 acceptance §7.3 #2 (cross-source identity): phone-shaped
iMessage handles must resolve to kind='phone' so they collide with
phones already stored from a Gmail correspondent and merge into one
people row. Email-shaped handles → 'email'. Fallback for unparseable
handles is 'imessage_handle'.

The IMessagePlugin's save path calls this before find_or_create_person
so cross-source identity unification is automatic for the common cases
(SMS phones, iCloud Apple Account emails).
EOF
)"
```

---

### Task 7: IMessagePlugin — 5 lifecycle hooks

**Files:**
- Create: `src/accountpilot/plugins/imessage/plugin.py`
- Create: `tests/accountpilot/plugins/imessage/test_plugin.py`

Implements the 5-hook contract. setup is informational. backfill walks chat.db end-to-end. sync_once reads since the watermark and saves each row through Storage. daemon starts the watcher and runs sync_once on each debounced fire. teardown stops the watcher.

The `save_imessage` path needs the cross-source kind dispatch from Task 6. We can't pass arbitrary kinds through `Storage.save_imessage` today — it hard-codes `kind='imessage_handle'` when calling `find_or_create_person` (per SP1 SP0 Task 11). Two options:
- (a) Add a parameter to `save_imessage` to override the kind.
- (b) Pre-resolve people in the plugin and pass `pid` lists to `Storage`.

Option (b) is closer to SP0's invariant ("plugins don't pick filenames or allocate IDs") — but requires a new Storage method. Option (a) is smaller, but bleeds source-specific knowledge into the façade. Pick (a) since SP0's `Storage.save_imessage` already knows about iMessage; we're just letting it use a smarter default for the handle kind.

- [ ] **Step 1: Make `Storage.save_imessage` use cross-source kind dispatch**

Modify `src/accountpilot/core/storage.py` — find the lines in `save_imessage` that call `find_or_create_person` for sender + each participant. They currently pass `kind="imessage_handle"`. Replace with:

```python
            from accountpilot.core.identity import kind_for_imessage_handle
            sender_kind = kind_for_imessage_handle(msg.sender_handle)
            sender_pid = await find_or_create_person(
                self.db, kind=sender_kind, value=msg.sender_handle,
                default_name=None,
            )
            await self.db.execute(
                "INSERT OR IGNORE INTO message_people "
                "(message_id, person_id, role) VALUES (?, ?, 'from')",
                (message_id, sender_pid),
            )
            for handle in msg.participants:
                ph_kind = kind_for_imessage_handle(handle)
                pid = await find_or_create_person(
                    self.db, kind=ph_kind, value=handle, default_name=None,
                )
                await self.db.execute(
                    "INSERT OR IGNORE INTO message_people "
                    "(message_id, person_id, role) VALUES (?, ?, 'participant')",
                    (message_id, pid),
                )
```

(The exact context varies; replace whichever block previously hard-coded `kind="imessage_handle"`.)

- [ ] **Step 2: Update an existing storage test to reflect the new dispatch**

In `tests/accountpilot/unit/core/test_storage_save_imessage.py`, the test that uses sender_handle `"+15551234567"` and participants `["+15551234567", "+15559876543"]` — those will now create `people` rows under `kind='phone'`, not `kind='imessage_handle'`. Update assertions if they query `identifiers` by kind. If they only check `message_people.role`, no change is needed. (Read the file first; adjust as required.)

- [ ] **Step 3: Run all unit tests**

```bash
pytest tests/accountpilot/unit -q
```

Expected: all green. If any test asserts `kind='imessage_handle'` on a phone-shaped handle, update it to `kind='phone'`.

- [ ] **Step 4: Write the IMessagePlugin failing test**

`tests/accountpilot/plugins/imessage/test_plugin.py`:

```python
from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage
from accountpilot.plugins.imessage.config import (
    IMessageAccountConfig,
    IMessagePluginConfig,
)
from accountpilot.plugins.imessage.plugin import IMessagePlugin
from accountpilot.plugins.imessage.reader import ChatDbReader
from tests.accountpilot.plugins.imessage.conftest import (
    add_chat_participant,
    insert_chat,
    insert_handle,
    insert_message,
)


async def _seed_account(storage: Storage, identifier: str) -> int:
    owner = await storage.upsert_owner(
        name="Aren", surname=None,
        identifiers=[Identifier(kind="phone", value=identifier)],
    )
    return await storage.upsert_account(
        source="imessage", identifier=identifier, owner_id=owner,
    )


async def test_sync_once_ingests_chat_db_messages(
    tmp_db_path: Path, tmp_runtime: Path, chatdb_path: Path,
) -> None:
    me = "+15551234567"
    melis = "+905052490140"

    # Seed synthetic chat.db with one inbound message from melis.
    h_me = insert_handle(chatdb_path, identifier=me)
    h_melis = insert_handle(chatdb_path, identifier=melis)
    chat = insert_chat(chatdb_path, guid=f"iMessage;-;{melis}",
                       identifier=melis)
    add_chat_participant(chatdb_path, chat_rowid=chat, handle_rowid=h_me)
    add_chat_participant(chatdb_path, chat_rowid=chat, handle_rowid=h_melis)
    insert_message(
        chatdb_path, guid="GUID-1", text="hi",
        handle_rowid=h_melis, chat_rowid=chat,
        sent_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
    )

    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        account_id = await _seed_account(storage, me)

        cfg = IMessagePluginConfig(accounts=[IMessageAccountConfig(
            identifier=me, owner=me, chat_db_path=chatdb_path,
        )])
        plugin = IMessagePlugin(
            config=cfg.model_dump(), storage=storage, secrets=Secrets({}),
        )
        await plugin.setup()
        await plugin.sync_once(account_id)

        async with db.execute("SELECT COUNT(*) AS c FROM messages") as cur:
            assert (await cur.fetchone())["c"] == 1
        async with db.execute(
            "SELECT chat_guid FROM imessage_details"
        ) as cur:
            row = await cur.fetchone()
        assert row["chat_guid"] == f"iMessage;-;{melis}"


async def test_sync_once_resolves_phone_handle_as_kind_phone(
    tmp_db_path: Path, tmp_runtime: Path, chatdb_path: Path,
) -> None:
    """Cross-source identity: a phone-shaped iMessage handle should
    create an `identifiers` row with kind='phone', not 'imessage_handle'."""
    h = insert_handle(chatdb_path, identifier="+15559876543")
    chat = insert_chat(chatdb_path, guid="c1")
    insert_message(chatdb_path, guid="m1", text="x", handle_rowid=h,
                   chat_rowid=chat,
                   sent_at=datetime(2026, 5, 1, tzinfo=UTC))

    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        account_id = await _seed_account(storage, "+15551234567")
        cfg = IMessagePluginConfig(accounts=[IMessageAccountConfig(
            identifier="+15551234567", owner="+15551234567",
            chat_db_path=chatdb_path,
        )])
        plugin = IMessagePlugin(
            config=cfg.model_dump(), storage=storage, secrets=Secrets({}),
        )
        await plugin.sync_once(account_id)

        async with db.execute(
            "SELECT kind FROM identifiers WHERE value=?",
            ("+15559876543",),
        ) as cur:
            row = await cur.fetchone()
        assert row is not None
        assert row["kind"] == "phone"


async def test_backfill_marks_accounts_backfilled_at(
    tmp_db_path: Path, tmp_runtime: Path, chatdb_path: Path,
) -> None:
    h = insert_handle(chatdb_path, identifier="+1")
    chat = insert_chat(chatdb_path, guid="c1")
    insert_message(chatdb_path, guid="m1", text="x", handle_rowid=h,
                   chat_rowid=chat,
                   sent_at=datetime(2026, 5, 1, tzinfo=UTC))

    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        account_id = await _seed_account(storage, "+15551234567")
        cfg = IMessagePluginConfig(accounts=[IMessageAccountConfig(
            identifier="+15551234567", owner="+15551234567",
            chat_db_path=chatdb_path,
        )])
        plugin = IMessagePlugin(
            config=cfg.model_dump(), storage=storage, secrets=Secrets({}),
        )
        await plugin.backfill(account_id)

        async with db.execute(
            "SELECT backfilled_at FROM accounts WHERE id=?", (account_id,)
        ) as cur:
            row = await cur.fetchone()
        assert row["backfilled_at"] is not None
```

- [ ] **Step 5: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/imessage/test_plugin.py -v
```

Expected: ImportError on `accountpilot.plugins.imessage.plugin`.

- [ ] **Step 6: Implement `src/accountpilot/plugins/imessage/plugin.py`**

```python
"""IMessagePlugin — 5-hook AccountPilotPlugin contract for iMessage."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from accountpilot.core.auth import Secrets
from accountpilot.core.plugin import AccountPilotPlugin
from accountpilot.plugins.imessage.config import (
    IMessageAccountConfig,
    IMessagePluginConfig,
)
from accountpilot.plugins.imessage.reader import (
    ChatDbReader,
    _APPLE_EPOCH,
)
from accountpilot.plugins.imessage.watcher import ChatDbWatcher

log = logging.getLogger(__name__)


def _datetime_to_apple_ns(dt: datetime) -> int:
    delta = dt - _APPLE_EPOCH
    return int(delta.total_seconds() * 1_000_000_000)


class IMessagePlugin(AccountPilotPlugin):
    """iMessage source plugin: chat.db reader + file-watcher daemon."""

    name: ClassVar[str] = "imessage"

    def __init__(
        self, config: dict[str, Any], storage: Any, secrets: Secrets,
    ) -> None:
        super().__init__(config=config, storage=storage, secrets=secrets)
        self._cfg = IMessagePluginConfig.model_validate(config)
        self._accounts: dict[str, IMessageAccountConfig] = {
            a.identifier: a for a in self._cfg.accounts
        }
        # Test seam: tests inject an alternate reader factory if needed.
        self._reader_factory = self._make_real_reader
        self._watcher: ChatDbWatcher | None = None

    def _make_real_reader(
        self, account: IMessageAccountConfig, account_id: int,
    ) -> ChatDbReader:
        return ChatDbReader(account.chat_db_path, account_id=account_id)

    async def _resolve_account(self, account_id: int) -> IMessageAccountConfig:
        async with self.storage.db.execute(
            "SELECT account_identifier FROM accounts WHERE id=?",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            raise LookupError(f"account_id={account_id} not in DB")
        identifier = str(row["account_identifier"])
        if identifier not in self._accounts:
            raise LookupError(
                f"account_id={account_id} (identifier={identifier!r}) is not "
                f"configured in plugins.imessage.accounts in config.yaml"
            )
        return self._accounts[identifier]

    # ─── Lifecycle hooks ───────────────────────────────────────────────────

    async def setup(self) -> None:
        log.info(
            "imessage plugin setup: %d account(s) configured",
            len(self._accounts),
        )

    async def backfill(
        self, account_id: int, *, since: datetime | None = None,
    ) -> None:
        await self.sync_once(account_id, since=since)
        await self._mark_backfilled(account_id)

    async def sync_once(
        self, account_id: int, *, since: datetime | None = None,
    ) -> None:
        account = await self._resolve_account(account_id)
        # Watermark: if `since` was provided, use it; else read the
        # latest sent_at we've already stored for this account.
        if since is None:
            since = await self.storage.latest_sent_at(account_id)
        since_ns = _datetime_to_apple_ns(since) if since else None

        reader = self._reader_factory(account, account_id)
        inserted = 0
        skipped = 0
        try:
            for msg in reader.read_messages(since_ns=since_ns):
                result = await self.storage.save_imessage(msg)
                if result.action == "inserted":
                    inserted += 1
                elif result.action == "skipped":
                    skipped += 1
            await self.storage.update_sync_status(
                account_id, success=True, messages_added=inserted,
            )
            log.info(
                "imessage sync_once account=%d inserted=%d skipped=%d",
                account_id, inserted, skipped,
            )
        except Exception as e:
            await self.storage.update_sync_status(
                account_id, success=False,
                error=f"{type(e).__name__}: {e}",
            )
            raise

    async def daemon(self, account_id: int) -> None:
        account = await self._resolve_account(account_id)

        # Run sync_once at startup to catch up since the last shutdown.
        await self.sync_once(account_id)

        # Bridge the watcher's threading.Timer callback into asyncio.
        loop = asyncio.get_running_loop()
        sync_event = asyncio.Event()

        def _on_change() -> None:
            loop.call_soon_threadsafe(sync_event.set)

        self._watcher = ChatDbWatcher(
            account.chat_db_path,
            on_change=_on_change,
            debounce_seconds=self._cfg.debounce_seconds,
        )
        self._watcher.start()
        log.info("imessage daemon started for account=%d", account_id)
        try:
            while True:
                await sync_event.wait()
                sync_event.clear()
                try:
                    await self.sync_once(account_id)
                except Exception:  # noqa: BLE001
                    log.exception("imessage sync_once failed; will retry on next event")
        finally:
            self._watcher.stop()
            self._watcher = None

    async def teardown(self) -> None:
        if self._watcher is not None:
            self._watcher.stop()
            self._watcher = None
        log.info("imessage plugin teardown")

    # ─── Internals ─────────────────────────────────────────────────────────

    async def _mark_backfilled(self, account_id: int) -> None:
        await self.storage.db.execute(
            "UPDATE accounts SET backfilled_at=? WHERE id=?",
            (datetime.now(UTC).isoformat(), account_id),
        )
        await self.storage.db.commit()
```

- [ ] **Step 7: Run tests pass**

```bash
pytest tests/accountpilot/plugins/imessage -v
```

Expected: all green.

- [ ] **Step 8: Commit**

```bash
git add src/accountpilot/core/storage.py src/accountpilot/plugins/imessage/plugin.py tests/accountpilot/plugins/imessage/test_plugin.py
git commit -m "$(cat <<'EOF'
feat(plugins/imessage): IMessagePlugin with 5 lifecycle hooks

setup, backfill, sync_once, daemon, teardown — implementing the SP0
AccountPilotPlugin contract for iMessage. setup is informational;
backfill = sync_once + accounts.backfilled_at update; sync_once reads
chat.db rows newer than Storage.latest_sent_at and saves each via
storage.save_imessage; daemon starts ChatDbWatcher + runs sync_once on
each debounced fire (asyncio.Event bridge from threading.Timer);
teardown stops the watcher.

Storage.save_imessage now uses kind_for_imessage_handle to dispatch
phone-shaped handles to kind='phone' (acceptance §7.3 #2: cross-source
identity collisions with Gmail correspondents). Email-shaped handles →
kind='email'. The default 'imessage_handle' remains for true Apple
Account / Game Center handles.
EOF
)"
```

---

### Task 8: imessage CLI subcommands

**Files:**
- Create: `src/accountpilot/plugins/imessage/cli.py`
- Create: `tests/accountpilot/plugins/imessage/test_cli.py`

`accountpilot imessage {backfill, sync, daemon}`. Identical shape to the mail CLI; the entry-point discovery loop in `cli.py` (SP1 Task 14) auto-registers the `imessage_group` Click group.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/plugins/imessage/test_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli


def test_imessage_subgroup_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["imessage", "--help"])
    assert result.exit_code == 0, result.output
    assert "backfill" in result.output
    assert "sync" in result.output
    assert "daemon" in result.output


def test_imessage_sync_with_missing_config_errors_cleanly(
    tmp_db_path: Path,
) -> None:
    runner = CliRunner()
    missing_cfg = tmp_db_path.parent / "no-such-config.yaml"
    result = runner.invoke(cli, [
        "imessage", "sync", "1",
        "--db-path", str(tmp_db_path),
        "--config", str(missing_cfg),
    ])
    assert result.exit_code != 0
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/imessage/test_cli.py -v
```

Expected: failure on missing `imessage` subcommand.

- [ ] **Step 3: Implement `src/accountpilot/plugins/imessage/cli.py`**

```python
"""accountpilot imessage CLI subgroup."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import click

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.config import load_config
from accountpilot.core.db.connection import open_db
from accountpilot.core.storage import Storage
from accountpilot.plugins.imessage.plugin import IMessagePlugin


@click.group("imessage")
def imessage_group() -> None:
    """iMessage plugin commands (backfill, sync, daemon)."""


def _db_option(f: Any) -> Any:
    return click.option(
        "--db-path",
        type=click.Path(path_type=Path),
        default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
    )(f)


def _config_option(f: Any) -> Any:
    return click.option(
        "--config",
        "config_path",
        type=click.Path(path_type=Path),
        default=Path.home() / ".config" / "accountpilot" / "config.yaml",
    )(f)


@asynccontextmanager
async def _opened_plugin(
    config_path: Path, db_path: Path,
) -> AsyncIterator[tuple[IMessagePlugin, Storage]]:
    cfg = load_config(config_path)
    im_cfg_raw = cfg.plugins.get("imessage")
    if im_cfg_raw is None or not im_cfg_raw.enabled:
        raise click.UsageError(
            f"no enabled `plugins.imessage` section in {config_path}"
        )
    # The SP0 generic AccountEntry has fields the imessage-specific
    # IMessageAccountConfig doesn't (provider, credentials_ref, etc.);
    # exclude_none + drop the mail-specific keys so model_validate
    # doesn't trip on extra='forbid'.
    im_cfg_dict: dict[str, Any] = {
        "accounts": [
            {
                k: v
                for k, v in a.model_dump(exclude_none=True).items()
                if k in {"identifier", "owner", "chat_db_path"}
            }
            for a in im_cfg_raw.accounts
        ],
        **im_cfg_raw.extra,
    }
    cas = CASStore(db_path.parent / "attachments")
    async with open_db(db_path) as db:
        storage = Storage(db, cas)
        plugin = IMessagePlugin(
            config=im_cfg_dict, storage=storage, secrets=Secrets({}),
        )
        yield plugin, storage


@imessage_group.command("backfill")
@click.argument("account_id", type=int)
@_db_option
@_config_option
def imessage_backfill(
    account_id: int, db_path: Path, config_path: Path,
) -> None:
    """One-shot historical pull from chat.db for an account."""

    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, _):
            await plugin.setup()
            await plugin.backfill(account_id)

    asyncio.run(_run())
    click.echo(f"backfill complete: account={account_id}")


@imessage_group.command("sync")
@click.argument("account_id", type=int)
@_db_option
@_config_option
def imessage_sync(
    account_id: int, db_path: Path, config_path: Path,
) -> None:
    """One incremental sync pass."""

    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, _):
            await plugin.setup()
            await plugin.sync_once(account_id)

    asyncio.run(_run())
    click.echo(f"sync complete: account={account_id}")


@imessage_group.command("daemon")
@_db_option
@_config_option
def imessage_daemon(db_path: Path, config_path: Path) -> None:
    """Long-running daemon: watches chat.db and syncs on each change."""

    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, storage):
            await plugin.setup()
            async with storage.db.execute(
                "SELECT id FROM accounts WHERE source='imessage' AND enabled=1"
            ) as cur:
                rows = [r["id"] for r in await cur.fetchall()]
            if not rows:
                raise click.UsageError(
                    "no enabled imessage accounts in DB"
                )
            await asyncio.gather(*(plugin.daemon(aid) for aid in rows))

    asyncio.run(_run())
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/plugins/imessage/test_cli.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/plugins/imessage/cli.py tests/accountpilot/plugins/imessage/test_cli.py
git commit -m "$(cat <<'EOF'
feat(plugins/imessage/cli): add accountpilot imessage {backfill,sync,daemon}

Three subcommands mirroring the mail plugin:
- imessage backfill <account_id>: one-shot history pull, marks
  accounts.backfilled_at on success.
- imessage sync <account_id>: one incremental pass.
- imessage daemon: long-running, watches chat.db via ChatDbWatcher
  and runs sync_once on each debounced modification.

The entry-point-discovery loop in src/accountpilot/cli.py (SP1
Task 14) registers `imessage_group` automatically by convention; no
changes needed in the root CLI.

The CLI strips the mail-specific keys (provider, credentials_ref) from
the SP0 generic AccountEntry dump before handing the config to
IMessagePlugin, since IMessageAccountConfig (extra=forbid) doesn't
share that shape.
EOF
)"
```

---

### Task 9: launchd plist (in infra repo)

**Files:**
- Create: `~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.imessage.daemon.plist`

Same shape as the mail daemon plist. Deploys to launchd alongside `com.accountpilot.mail.daemon`.

- [ ] **Step 1: Create the plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.accountpilot.imessage.daemon</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/ae/.venv/accountpilot/bin/accountpilot</string>
        <string>imessage</string>
        <string>daemon</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/ae/runtime/accountpilot/logs/imessage.daemon.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ae/runtime/accountpilot/logs/imessage.daemon.stderr.log</string>

    <key>WorkingDirectory</key>
    <string>/Users/ae/runtime/accountpilot</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin</string>
    </dict>
</dict>
</plist>
```

- [ ] **Step 2: Validate + commit (in infra repo)**

```bash
plutil -lint /Users/ae/Projects/infra/configs/machines/ae/launchd/com.accountpilot.imessage.daemon.plist

cd ~/Projects/infra
git add configs/machines/ae/launchd/com.accountpilot.imessage.daemon.plist
git commit -m "$(cat <<'EOF'
feat(ae/launchd): com.accountpilot.imessage.daemon job

Long-running imessage.daemon for AccountPilot AP-SP2. Runs
`accountpilot imessage daemon` under the user agent context. KeepAlive
revives on crash; logs stream to ~/runtime/accountpilot/logs/.

Bootstrap manually:
  launchctl bootstrap gui/$UID <plist>
  launchctl enable gui/$UID/com.accountpilot.imessage.daemon
  launchctl kickstart gui/$UID/com.accountpilot.imessage.daemon

The Python interpreter at the ProgramArguments[0] path needs Full Disk
Access granted in System Settings to read ~/Library/Messages/chat.db.
EOF
)"
cd /Users/ae/Code/account-pilot
```

Do NOT push the infra commit — the user reviews + pushes themselves.

---

### Task 10: Acceptance runbook (Full Disk Access caveat)

**Files:**
- Create: `docs/how-to/ap-sp2-acceptance-guide.md`
- Modify: `docs/how-to/README.md` (add the new guide to the index)

Mirror the SP1 runbook structure. The key new section is **Full Disk Access setup** — without FDA, sqlite3 returns `sqlite3.OperationalError: unable to open database file` and nothing works.

- [ ] **Step 1: Write `docs/how-to/ap-sp2-acceptance-guide.md`**

```markdown
# AP-SP2 Hardware Acceptance Guide

> **Last updated:** 2026-05-XX
> **Status:** Active
> **Audience:** Maintainer (AE) running the five hardware acceptance scenarios for sub-slice AP-SP2.

## Overview

Use this guide to run the five iMessage acceptance scenarios from spec
§7.3 on AE. Unlike SP1, there are no remote credentials — the data
source is the local `~/Library/Messages/chat.db` file. The one
critical setup step is **Full Disk Access** for whatever Python
interpreter runs the daemon.

## Prerequisites

- macOS host (any version since Big Sur).
- Existing AccountPilot install that already passed AP-SP1 acceptance.
- A second device or Apple ID that can send you an iMessage to test.
- 1 owner already declared in `~/.config/accountpilot/config.yaml` whose
  identifiers include the phone number tied to your iMessage account.

## Step 1: Grant Full Disk Access to the Python interpreter

1. Find the interpreter path:
   ```bash
   which python3
   readlink "$(which python3)"   # follow symlinks if needed
   ```

2. Open **System Settings → Privacy & Security → Full Disk Access**.

3. Click `+`, navigate to the Python binary's actual path (not a venv
   symlink — point at the real binary). Add it.

4. Confirm:
   ```bash
   sqlite3 -readonly "file:$HOME/Library/Messages/chat.db?mode=ro" "SELECT COUNT(*) FROM message"
   ```
   Expected: an integer printed (the message count). If you see
   `unable to open database file`, FDA is still missing.

If you use a venv, granting FDA to the venv's `python3` is not enough
— FDA is granted to the underlying interpreter binary that the venv
symlinks to. Always grant to the real binary.

## Step 2: Add the iMessage account to your config

Append to `~/.config/accountpilot/config.yaml`:

\```yaml
plugins:
  mail:
    # ... existing mail block unchanged ...
  imessage:
    enabled: true
    accounts:
      - identifier: "+15551234567"   # your iCloud phone, E.164
        owner: "+15551234567"        # references owner identifier above
\```

The owner reference must match an existing owner identifier (the same
phone, ideally — declared in the `owners:` block).

## Step 3: Apply config

```bash
accountpilot setup
accountpilot status
```

Expected: a new `imessage` row alongside `gmail`. Note the `account_id`
(probably `2`):

```bash
IM_ACCOUNT_ID=2
```

## Step 4: Backfill

```bash
accountpilot imessage backfill $IM_ACCOUNT_ID
```

Pulls history. Time is proportional to chat.db size — typically a few
seconds for ~10k messages. Re-running is idempotent.

## Step 5: Run scenarios 1-5

### Scenario 1 — New iMessage arrives

Run the daemon (or use launchctl bootstrap):

```bash
accountpilot imessage daemon
```

From a second device, send yourself an iMessage with a unique phrase,
e.g. `AP-SP2 ECHO ALPHA-2026`.

In another terminal:

```bash
sleep 4   # one debounce window
accountpilot search 'ALPHA-2026'
```

**Pass criteria:** the message appears at the top of search results
within ~5s of arrival.

### Scenario 2 — Cross-source identity

Verify the iMessage sender resolves into the same `people` row as a
Gmail correspondent (assuming they share a phone number):

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db "
  SELECT p.id, p.name, GROUP_CONCAT(i.kind || ':' || i.value) AS idents
  FROM people p
  JOIN identifiers i ON i.person_id=p.id
  GROUP BY p.id
  HAVING COUNT(i.id) > 1
  LIMIT 10
"
```

**Pass criteria:** at least one row shows multiple kinds for the same
person (e.g. `email:foo@x.com,phone:+15551234567`). If not, send
yourself an iMessage from a number whose owner already has a Gmail
identifier in the DB.

### Scenario 3 — Group chat participants

Pick a group iMessage thread and verify all participants appear as
`participant` rows:

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db "
  SELECT m.id, m.body_text, COUNT(mp.person_id) AS people_n
  FROM messages m
  JOIN message_people mp ON mp.message_id = m.id
  WHERE m.source = 'imessage'
  GROUP BY m.id
  HAVING people_n > 2
  ORDER BY m.sent_at DESC
  LIMIT 5
"
```

**Pass criteria:** rows with `people_n >= 3` exist (you + sender + at
least one other participant).

### Scenario 4 — Attachment in CAS

Send yourself an iMessage with an attached image. Verify after sync:

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db "
  SELECT a.filename, a.content_hash, a.cas_path, a.size_bytes
  FROM attachments a
  JOIN messages m ON m.id = a.message_id
  WHERE m.source = 'imessage'
  ORDER BY a.id DESC
  LIMIT 1
"
```

Confirm the file exists and the hash matches:

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db \
  "SELECT cas_path, content_hash FROM attachments WHERE message_id IN (SELECT id FROM messages WHERE source='imessage') ORDER BY id DESC LIMIT 1" \
  | while IFS='|' read REL HASH; do
      FULL=~/runtime/accountpilot/attachments/"$REL"
      ls -la "$FULL"
      echo "expected: $HASH"
      echo "actual:   $(shasum -a 256 "$FULL" | cut -d' ' -f1)"
    done
```

**Pass criteria:** file exists, sha256 matches.

### Scenario 5 — chat.db rotation survival

Apple writes through SQLite WAL mode, so chat.db gets rotated /
checkpointed periodically. The watcher must keep firing across these
rotations and dedup must hold. Force one:

```bash
sqlite3 ~/Library/Messages/chat.db "PRAGMA wal_checkpoint(TRUNCATE);" 2>&1
```

(That command is harmless — it tells SQLite to checkpoint the WAL into
the main file.)

Then send a fresh iMessage and verify it lands. Check no duplicates:

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db "
  SELECT COUNT(*) AS total, COUNT(DISTINCT external_id) AS unique_msgids
  FROM messages WHERE source = 'imessage'
"
```

**Pass criteria:** `total == unique_msgids`. Daemon's last_error in
`accountpilot status` is empty.

## Step 6: Tag the slice

When 1-5 all pass:

\```bash
cd ~/Code/account-pilot
git tag -a ap-sp2-complete -m "$(cat <<'EOF'
AP-SP2 acceptance passed on AE.

5/5 hardware scenarios verified per spec §7.3:
1. New iMessage -> search returns it within ~5s of arrival.
2. Cross-source identity: shared phone collapses Gmail and iMessage
   correspondents into one people row.
3. Group chat -> >=3 message_people rows.
4. iMessage attachment -> CAS file + sha256 verifies.
5. chat.db WAL checkpoint survived; total == unique_msgids; no
   daemon errors.

Next slice: AP-SP3 (OAuth + multi-account + polish).
EOF
)"
git push origin ap-sp2-complete
\```

## Troubleshooting

### `sqlite3.OperationalError: unable to open database file`

Full Disk Access is missing for the Python interpreter actually
running the command. Re-check Step 1, point at the real binary not a
venv symlink, and re-launch your terminal session afterwards (Privacy
permissions update on a per-process basis).

### Watcher fires but no messages arrive

This is normal during chat.db rotation: the watcher debounces the
write burst and runs sync_once, which finds nothing new (because the
WAL checkpoint doesn't add messages). Verify with:

```bash
tail -f ~/runtime/accountpilot/logs/imessage.daemon.stdout.log
```

You should see periodic `inserted=0 skipped=0` lines.

### `attributedBody`-only messages show empty body

Confirmed SP2 limitation. Apple stores rich-content message bodies in
the `attributedBody` BLOB column (typedstream-encoded
`NSAttributedString`). SP2 reads only the plain `text` column. SP3
will add a typedstream decoder.

## Related documents

- `docs/plans/2026-05-02-accountpilot-ap-sp2.md` — implementation plan
  for this slice.
- `docs/specs/2026-05-01-storage-rewrite-design.md` §7.3 — five
  acceptance scenarios.
- `docs/how-to/ap-sp1-acceptance-guide.md` — the AP-SP1 mail-side
  runbook (companion).
```

- [ ] **Step 2: Update `docs/how-to/README.md`**

Add a row for the new guide:

```markdown
| [ap-sp2-acceptance-guide.md](ap-sp2-acceptance-guide.md) | Run the five hardware acceptance scenarios that gate AP-SP2 on AE. |
```

- [ ] **Step 3: Commit**

```bash
git add docs/how-to/ap-sp2-acceptance-guide.md docs/how-to/README.md
git commit -m "docs(how-to): add AP-SP2 hardware acceptance guide"
```

---

### Task 11: Documentation refresh

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`

Mark AP-SP2 done across the repo's metadata.

- [ ] **Step 1: Update `README.md` Status section**

Replace the AP-SP2 line:

```markdown
- **AP-SP2:** complete — iMessage plugin (file-watch on chat.db,
  attachment + group-chat support, cross-source identity).
- **AP-SP3:** next — OAuth, multi-account, polish.
```

- [ ] **Step 2: Update `CLAUDE.md` sub-slice ordering**

Mark AP-SP2 with `(✓ done)` in the ordering list. Update the "What
This Repo Is" paragraph if it mentions AP-SP2 as future work.

- [ ] **Step 3: Update `ROADMAP.md`**

Mark the AP-SP2 task list with `[x]` and the "Current Status" prose.

- [ ] **Step 4: Update `CHANGELOG.md`**

Add at top:

```markdown
## [Unreleased] — 2026-05-XX (AP-SP2)

### Added
- iMessage plugin under `accountpilot.plugins.imessage`: ChatDbReader
  (read-only sqlite3 over `~/Library/Messages/chat.db`),
  AttachmentReader (loads attachment bytes with `~` expansion),
  ChatDbWatcher (watchdog file-watcher with debounce), IMessagePlugin
  (5-hook lifecycle), `imessage backfill/sync/daemon` CLI subcommands.
- `kind_for_imessage_handle` in `core/identity.py` — dispatches
  iMessage handles to `kind='phone'` / `kind='email'` /
  `kind='imessage_handle'` for cross-source identity unification with
  Gmail correspondents.
- `~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.imessage.daemon.plist`
  for AE deployment.
- `docs/how-to/ap-sp2-acceptance-guide.md` runbook.

### Changed
- `pyproject.toml` adds `watchdog>=4.0` dependency and registers the
  `imessage` plugin entry point.
- `Storage.save_imessage` resolves sender/participant handles via
  `kind_for_imessage_handle` instead of hard-coding
  `kind='imessage_handle'`.
```

- [ ] **Step 5: Verify + commit**

```bash
pytest tests/accountpilot -q
ruff check src/accountpilot tests/accountpilot
mypy src/accountpilot

git add README.md CLAUDE.md ROADMAP.md CHANGELOG.md
git commit -m "docs: AP-SP2 status — iMessage plugin complete"
```

---

### Task 12: Hardware acceptance (manual on AE)

**Files:** none modified — execution only.

Follow the runbook at `docs/how-to/ap-sp2-acceptance-guide.md`. When
all five scenarios pass, run the `git tag ap-sp2-complete` from Step 6
of the runbook.

If any scenario fails, open a follow-up entry in
`docs/plans/2026-05-02-accountpilot-ap-sp2.md` with the symptom and
fix before tagging.

---

## Summary of commits

| # | Subject |
|---|---------|
| 1  | chore: register imessage plugin + add watchdog dep |
| 2  | feat(plugins/imessage): config models |
| 3  | feat(plugins/imessage): chat.db reader |
| 4  | feat(plugins/imessage): attachment reader + integration into ChatDbReader |
| 5  | feat(plugins/imessage): chat.db file watcher with debounce |
| 6  | feat(core/identity): add kind_for_imessage_handle dispatch helper |
| 7  | feat(plugins/imessage): IMessagePlugin with 5 lifecycle hooks |
| 8  | feat(plugins/imessage/cli): add accountpilot imessage {backfill,sync,daemon} |
| 9  | feat(ae/launchd): com.accountpilot.imessage.daemon job (in infra repo) |
| 10 | docs(how-to): add AP-SP2 hardware acceptance guide |
| 11 | docs: AP-SP2 status — iMessage plugin complete |
| 12 | (acceptance — no commit; produces tag `ap-sp2-complete`) |
