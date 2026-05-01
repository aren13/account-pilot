# AccountPilot AP-SP0 — Core Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `accountpilot.core` end-to-end — schema, Storage façade, Pydantic models, identity resolution, CAS attachment writer, plugin loader, config loader, CLI scaffolding, migrations — and prove the contract with a synthetic plugin. No real plugins yet; `mailpilot` continues to ship in parallel.

**Architecture:** Single SQLite DB at `~/runtime/accountpilot/accountpilot.db` written exclusively through a typed `Storage` façade. Plugins discovered via `importlib.metadata` entry points. Click-based CLI dispatches to plugin subcommands and core admin commands. Attachments live in a content-addressed store on disk. Identity is first-class: a unified `people` table with an `identifiers` map handles cross-source person resolution.

**Tech Stack:** Python 3.11+, aiosqlite, Pydantic v2, Click, PyYAML, phonenumbers, pytest + pytest-asyncio. Existing project conventions retained (Hatchling, Ruff, strict mypy, pre-commit).

**Reference spec:** `docs/specs/2026-05-01-storage-rewrite-design.md` — read this first if anything in this plan is ambiguous.

---

## File Structure

**Created:**

```
src/accountpilot/
  __init__.py
  __main__.py
  cli.py                              # Click root group, registers subcommands
  core/
    __init__.py
    config.py                         # YAML loader → Pydantic Config models
    storage.py                        # Storage façade — sole DB+CAS writer
    models.py                         # EmailMessage, IMessageMessage, AttachmentBlob, Identifier, SaveResult
    identity.py                       # normalize_*, find_or_create_person, merge_people
    cas.py                            # content-addressed attachment writer
    auth.py                           # secrets resolution stub (real impl in SP1)
    plugin.py                         # AccountPilotPlugin base class + entry-point discovery
    db/
      __init__.py
      connection.py                   # async SQLite connection with WAL+FK pragmas
      migrations.py                   # migration runner
      migrations/
        001_init.sql                  # all 9 tables + FTS5 + triggers
    cli/
      __init__.py
      db_cmds.py                      # accountpilot db {migrate,vacuum}
      people_cmds.py                  # accountpilot people {list,show,merge,promote,demote}
      accounts_cmds.py                # accountpilot accounts {list,add,disable,delete}
      setup_cmd.py                    # accountpilot setup
      status_cmd.py                   # accountpilot status
      search_cmd.py                   # accountpilot search

tests/
  accountpilot/
    __init__.py
    conftest.py                       # shared fixtures (tmp_db, tmp_runtime)
    unit/
      __init__.py
      core/
        __init__.py
        test_models.py
        test_identity_normalize.py
        test_identity_find_or_create.py
        test_identity_merge.py
        test_cas.py
        test_storage_save_email.py
        test_storage_save_imessage.py
        test_storage_helpers.py
        test_db_migrations.py
        test_config.py
        test_plugin_base.py
      cli/
        __init__.py
        test_db_cmds.py
        test_people_cmds.py
        test_accounts_cmds.py
        test_setup_cmd.py
        test_status_cmd.py
        test_search_cmd.py
    integration/
      __init__.py
      test_synthetic_plugin.py
    fixtures/
      __init__.py
      synthetic_plugin/
        __init__.py
        plugin.py                     # emits one fake email + one fake iMessage
```

**Modified:**

```
pyproject.toml                        # add accountpilot package + new deps + new scripts
README.md                             # short note pointing to design doc; full rewrite in SP3
```

**Untouched (deleted in SP1):** all of `src/mailpilot/`, `tests/test_*.py`.

---

## Pre-flight Notes

- **Python version:** 3.11+, matching existing `requires-python`.
- **Async:** all DB I/O via `aiosqlite`. Storage methods are `async`. Tests use `pytest-asyncio` (`@pytest.mark.asyncio`).
- **Test isolation:** every DB-touching test gets a fresh temp DB via the `tmp_db` fixture in `tests/accountpilot/conftest.py`.
- **TDD discipline:** every task writes the failing test first, runs it to confirm it fails, implements, runs again to confirm pass.
- **Commits:** one commit per task, conventional format (`feat:`, `test:`, `chore:`). Do not bundle multiple tasks into one commit.
- **Working branch:** `main` is acceptable for SP0 since `mailpilot` keeps shipping unchanged. If a longer feature branch is preferred, branch off before Task 1.

---

### Task 1: Repo bootstrap — package skeleton + pyproject changes

**Files:**
- Create: `src/accountpilot/__init__.py`
- Create: `src/accountpilot/__main__.py`
- Create: `src/accountpilot/cli.py` (skeleton only)
- Create: `src/accountpilot/core/__init__.py`
- Create: `src/accountpilot/core/db/__init__.py`
- Create: `src/accountpilot/core/db/migrations/__init__.py`
- Create: `src/accountpilot/core/cli/__init__.py`
- Create: `src/accountpilot/plugins/__init__.py`
- Create: `tests/__init__.py` (empty — needed so `from tests.accountpilot…` imports resolve)
- Create: `tests/accountpilot/__init__.py`
- Create: `tests/accountpilot/unit/__init__.py`
- Create: `tests/accountpilot/unit/core/__init__.py`
- Create: `tests/accountpilot/unit/cli/__init__.py`
- Create: `tests/accountpilot/integration/__init__.py`
- Create: `tests/accountpilot/fixtures/__init__.py`
- Create: `tests/accountpilot/fixtures/synthetic_plugin/__init__.py`
- Create: `tests/accountpilot/conftest.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add accountpilot package + new deps + entry points to pyproject.toml**

In `pyproject.toml`, leave `mailpilot` package + script intact and add:

```toml
[project]
# ... existing fields kept ...
dependencies = [
    "aioimaplib",
    "aiosmtplib",
    "aiosqlite",
    "pydantic>=2.0",
    "click>=8.0",
    "pyyaml",
    "python-dateutil",
    "mail-parser",
    "msal",
    "phonenumbers>=8.13",     # NEW: E.164 normalization for identity
]

[project.scripts]
mailpilot = "mailpilot.cli:cli"
accountpilot = "accountpilot.cli:cli"  # NEW

[tool.hatch.build.targets.wheel]
packages = ["src/mailpilot", "src/accountpilot"]   # MODIFIED

[project.entry-points."accountpilot.plugins"]
# Plugins register here. SP0 ships none. The synthetic test plugin registers
# itself programmatically in tests, not via entry points.

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"          # NEW: pytest-asyncio runs all async tests automatically
pythonpath = [".", "src"]      # NEW: lets integration tests import tests.accountpilot.fixtures.*
```

- [ ] **Step 2: Create skeleton package files**

`src/accountpilot/__init__.py`:
```python
"""AccountPilot — unified account sync framework."""

__version__ = "0.1.0"
```

`src/accountpilot/__main__.py`:
```python
from accountpilot.cli import cli

if __name__ == "__main__":
    cli()
```

`src/accountpilot/cli.py` (skeleton, populated in later tasks):
```python
"""AccountPilot CLI root.

Subcommands are registered in this module. Plugin-contributed subcommands are
registered after entry-point discovery in core.plugin.load_plugins().
"""

import click


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


# Subcommand registrations are added in later tasks (db, people, accounts,
# setup, status, search).
```

Each `__init__.py` (core, core/db, core/db/migrations, core/cli, plugins) is empty.

- [ ] **Step 3: Create shared test fixtures**

All test `__init__.py` files (`tests/__init__.py`, `tests/accountpilot/__init__.py`, and the `unit/`, `unit/core/`, `unit/cli/`, `integration/`, `fixtures/`, `fixtures/synthetic_plugin/` subdirectories) are empty — they only exist so the directories are importable as packages. Create them all now; later tasks will populate the directories with test files.

`tests/accountpilot/conftest.py`:
```python
"""Shared fixtures for accountpilot tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest


@pytest.fixture
def tmp_runtime(tmp_path: Path) -> Path:
    """Temporary `~/runtime/accountpilot/`-equivalent for a test."""
    runtime = tmp_path / "runtime"
    (runtime / "attachments").mkdir(parents=True)
    (runtime / "logs").mkdir()
    (runtime / "tmp").mkdir()
    (runtime / "secrets").mkdir(mode=0o700)
    return runtime


@pytest.fixture
def tmp_db_path(tmp_runtime: Path) -> Path:
    """Path to a fresh, empty SQLite DB file for the test."""
    return tmp_runtime / "accountpilot.db"
```

(Real `tmp_db` async fixture that opens a connection + applies migrations is added in Task 4 once the connection helper exists.)

- [ ] **Step 4: Verify package importable + pytest collects**

Run:
```bash
uv pip install -e ".[dev]"
python -c "import accountpilot; print(accountpilot.__version__)"
pytest tests/accountpilot/ -q
```

Expected:
- `0.1.0` printed.
- pytest collects 0 tests, exits 0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/accountpilot tests/accountpilot
git commit -m "$(cat <<'EOF'
feat(core): bootstrap accountpilot package skeleton

Add the accountpilot package alongside mailpilot, register the
`accountpilot` console script, declare new dep (phonenumbers), and add
the `accountpilot.plugins` entry-point group used for plugin discovery
in later tasks.

Set up the tests/accountpilot/ tree with shared tmp_runtime and
tmp_db_path fixtures so subsequent DB-touching tests have a clean,
isolated SQLite path.

mailpilot remains shipped unchanged; both packages co-exist until SP1
deletes mailpilot.
EOF
)"
```

---

### Task 2: SQLite migration runner

**Files:**
- Create: `src/accountpilot/core/db/migrations.py`
- Test: `tests/accountpilot/unit/core/test_db_migrations.py`

The migration runner reads `.sql` files from `core/db/migrations/`, applies them in lexicographic order to a target DB, and tracks applied versions in a `schema_version` table. Idempotent: re-running is a no-op.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_db_migrations.py`:
```python
from __future__ import annotations

from pathlib import Path

import aiosqlite
import pytest

from accountpilot.core.db.migrations import apply_migrations, current_version


async def _table_exists(db: aiosqlite.Connection, name: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ) as cur:
        return (await cur.fetchone()) is not None


async def test_apply_migrations_creates_schema_version_and_applies_files(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY);"
    )
    (migrations_dir / "002_second.sql").write_text(
        "CREATE TABLE beta (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)
        assert await _table_exists(db, "schema_version")
        assert await _table_exists(db, "alpha")
        assert await _table_exists(db, "beta")
        assert await current_version(db) == 2


async def test_apply_migrations_is_idempotent(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)
        await apply_migrations(db, migrations_dir)  # second run, no error
        assert await current_version(db) == 1


async def test_apply_migrations_only_applies_new(
    tmp_db_path: Path, tmp_path: Path
) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "001_first.sql").write_text(
        "CREATE TABLE alpha (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)

    (migrations_dir / "002_second.sql").write_text(
        "CREATE TABLE beta (id INTEGER PRIMARY KEY);"
    )

    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, migrations_dir)
        assert await current_version(db) == 2
        assert await _table_exists(db, "alpha")
        assert await _table_exists(db, "beta")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/accountpilot/unit/core/test_db_migrations.py -v`
Expected: ImportError on `accountpilot.core.db.migrations`.

- [ ] **Step 3: Implement the migration runner**

`src/accountpilot/core/db/migrations.py`:
```python
"""SQLite migration runner.

Applies numbered .sql files from a migrations directory in lexicographic order.
Tracks applied versions in a `schema_version` table. Idempotent.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

_SCHEMA_VERSION_DDL = """
CREATE TABLE IF NOT EXISTS schema_version (
    version    INTEGER PRIMARY KEY,
    filename   TEXT NOT NULL,
    applied_at TIMESTAMP NOT NULL
);
"""

_FILENAME_RE = re.compile(r"^(\d+)_.+\.sql$")


async def current_version(db: aiosqlite.Connection) -> int:
    """Return the highest applied migration version, or 0 if none."""
    await db.execute(_SCHEMA_VERSION_DDL)
    async with db.execute("SELECT MAX(version) FROM schema_version") as cur:
        row = await cur.fetchone()
    return int(row[0]) if row and row[0] is not None else 0


async def apply_migrations(
    db: aiosqlite.Connection, migrations_dir: Path
) -> list[int]:
    """Apply all migrations in `migrations_dir` newer than `current_version(db)`.

    Returns the list of versions newly applied (empty if up-to-date).
    """
    await db.execute(_SCHEMA_VERSION_DDL)
    applied = await current_version(db)
    newly_applied: list[int] = []

    for path in sorted(migrations_dir.iterdir()):
        match = _FILENAME_RE.match(path.name)
        if match is None:
            continue
        version = int(match.group(1))
        if version <= applied:
            continue
        sql = path.read_text()
        await db.executescript(sql)
        await db.execute(
            "INSERT INTO schema_version (version, filename, applied_at) "
            "VALUES (?, ?, ?)",
            (version, path.name, datetime.now(UTC).isoformat()),
        )
        await db.commit()
        newly_applied.append(version)

    return newly_applied
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/accountpilot/unit/core/test_db_migrations.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/db/migrations.py tests/accountpilot/unit/core/test_db_migrations.py
git commit -m "$(cat <<'EOF'
feat(core/db): add SQLite migration runner

Read numbered .sql files from a migrations directory and apply each in
order, tracking applied versions in a schema_version table. Idempotent
re-runs become no-ops; new files added later are applied without
re-applying old ones.
EOF
)"
```

---

### Task 3: Initial schema migration `001_init.sql`

**Files:**
- Create: `src/accountpilot/core/db/migrations/001_init.sql`
- Test: extend `tests/accountpilot/unit/core/test_db_migrations.py`

Implements the full 9-table schema from spec §4 plus the FTS5 triggers. Uses a **plain (not contentless) FTS5 table** for simplicity — the contentless form makes deletes/joins awkward and the storage cost is acceptable for v1.

- [ ] **Step 1: Write the failing test**

Append to `tests/accountpilot/unit/core/test_db_migrations.py`:
```python
import accountpilot.core.db.migrations as _migrations_pkg  # noqa: E402

PROJECT_MIGRATIONS_DIR = (
    Path(_migrations_pkg.__file__).parent / "migrations"
)


async def _columns(db: aiosqlite.Connection, table: str) -> list[str]:
    async with db.execute(f"PRAGMA table_info({table})") as cur:
        return [row[1] for row in await cur.fetchall()]


async def test_001_init_creates_all_tables(tmp_db_path: Path) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        for table in [
            "people",
            "identifiers",
            "accounts",
            "messages",
            "email_details",
            "imessage_details",
            "message_people",
            "attachments",
            "messages_fts",
            "sync_status",
        ]:
            assert await _table_exists(db, table), f"missing table: {table}"


async def test_001_init_people_columns(tmp_db_path: Path) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        cols = await _columns(db, "people")
    assert {"id", "name", "surname", "is_owner", "notes",
            "created_at", "updated_at"} <= set(cols)


async def test_001_init_unique_identifier(tmp_db_path: Path) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        await db.execute(
            "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
            "VALUES ('A', NULL, 0, '2026-05-01', '2026-05-01')"
        )
        await db.execute(
            "INSERT INTO identifiers (person_id, kind, value, is_primary, created_at) "
            "VALUES (1, 'email', 'x@y.com', 0, '2026-05-01')"
        )
        with pytest.raises(aiosqlite.IntegrityError):
            await db.execute(
                "INSERT INTO identifiers (person_id, kind, value, is_primary, created_at) "
                "VALUES (1, 'email', 'x@y.com', 0, '2026-05-01')"
            )


async def test_001_init_fts_trigger_indexes_body_and_subject(
    tmp_db_path: Path,
) -> None:
    async with aiosqlite.connect(tmp_db_path) as db:
        await db.execute("PRAGMA foreign_keys = ON")
        await apply_migrations(db, PROJECT_MIGRATIONS_DIR)
        # Set up minimal owner+account so we can insert a message.
        await db.executescript("""
            INSERT INTO people (name, surname, is_owner, created_at, updated_at)
              VALUES ('Aren', 'E', 1, '2026-05-01', '2026-05-01');
            INSERT INTO accounts (
              owner_id, source, account_identifier, enabled, created_at, updated_at
            ) VALUES (1, 'gmail', 'a@b.com', 1, '2026-05-01', '2026-05-01');
            INSERT INTO messages (
              account_id, source, external_id, sent_at, body_text,
              direction, created_at
            ) VALUES (
              1, 'gmail', 'mid-1', '2026-05-01', 'lorem ipsum dolor',
              'inbound', '2026-05-01'
            );
            INSERT INTO email_details (
              message_id, subject, imap_uid, mailbox
            ) VALUES (1, 'Hello world', 42, 'INBOX');
        """)
        await db.commit()
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'lorem'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'world'"
        ) as cur:
            assert (await cur.fetchone())[0] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/accountpilot/unit/core/test_db_migrations.py -v`
Expected: failures on the four new tests because `001_init.sql` does not exist.

- [ ] **Step 3: Write the migration**

`src/accountpilot/core/db/migrations/001_init.sql`:
```sql
-- Identity layer ----------------------------------------------------------

CREATE TABLE people (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    surname     TEXT,
    is_owner    INTEGER NOT NULL DEFAULT 0,
    notes       TEXT,
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP NOT NULL
);

CREATE TABLE identifiers (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    value       TEXT NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL,
    UNIQUE (kind, value)
);
CREATE INDEX idx_identifiers_person ON identifiers(person_id);

CREATE TABLE accounts (
    id                  INTEGER PRIMARY KEY,
    owner_id            INTEGER NOT NULL REFERENCES people(id),
    source              TEXT NOT NULL,
    account_identifier  TEXT NOT NULL,
    display_name        TEXT,
    credentials_ref     TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1,
    backfilled_at       TIMESTAMP,
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL,
    UNIQUE (source, account_identifier)
);

-- Message layer -----------------------------------------------------------

CREATE TABLE messages (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    thread_id    TEXT,
    sent_at      TIMESTAMP NOT NULL,
    received_at  TIMESTAMP,
    body_text    TEXT NOT NULL DEFAULT '',
    body_html    TEXT,
    direction    TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL,
    UNIQUE (account_id, external_id)
);
CREATE INDEX idx_messages_thread  ON messages(thread_id);
CREATE INDEX idx_messages_sent_at ON messages(sent_at);
CREATE INDEX idx_messages_account ON messages(account_id);

CREATE TABLE email_details (
    message_id        INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    subject           TEXT NOT NULL DEFAULT '',
    in_reply_to       TEXT,
    references_json   TEXT,
    imap_uid          INTEGER NOT NULL,
    mailbox           TEXT NOT NULL,
    gmail_thread_id   TEXT,
    labels_json       TEXT,
    raw_headers_json  TEXT
);

CREATE TABLE imessage_details (
    message_id   INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    chat_guid    TEXT NOT NULL,
    service      TEXT NOT NULL,
    is_from_me   INTEGER NOT NULL,
    is_read      INTEGER NOT NULL DEFAULT 0,
    date_read    TIMESTAMP
);

CREATE TABLE message_people (
    message_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    person_id    INTEGER NOT NULL REFERENCES people(id),
    role         TEXT NOT NULL,
    PRIMARY KEY (message_id, person_id, role)
);
CREATE INDEX idx_message_people_person ON message_people(person_id);

CREATE TABLE attachments (
    id            INTEGER PRIMARY KEY,
    message_id    INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    mime_type     TEXT,
    size_bytes    INTEGER NOT NULL,
    cas_path      TEXT NOT NULL
);
CREATE INDEX idx_attachments_message ON attachments(message_id);
CREATE INDEX idx_attachments_hash    ON attachments(content_hash);

-- Search layer ------------------------------------------------------------

CREATE VIRTUAL TABLE messages_fts USING fts5(
    body_text,
    subject,
    tokenize = 'porter unicode61'
);

CREATE TRIGGER messages_fts_insert
AFTER INSERT ON messages
BEGIN
    INSERT INTO messages_fts(rowid, body_text, subject)
    VALUES (NEW.id, NEW.body_text, '');
END;

CREATE TRIGGER messages_fts_update_body
AFTER UPDATE OF body_text ON messages
BEGIN
    UPDATE messages_fts SET body_text = NEW.body_text WHERE rowid = NEW.id;
END;

CREATE TRIGGER messages_fts_delete
AFTER DELETE ON messages
BEGIN
    DELETE FROM messages_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER email_details_fts_insert
AFTER INSERT ON email_details
BEGIN
    UPDATE messages_fts SET subject = NEW.subject WHERE rowid = NEW.message_id;
END;

CREATE TRIGGER email_details_fts_update
AFTER UPDATE OF subject ON email_details
BEGIN
    UPDATE messages_fts SET subject = NEW.subject WHERE rowid = NEW.message_id;
END;

-- Operational state -------------------------------------------------------

CREATE TABLE sync_status (
    account_id            INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    last_sync_at          TIMESTAMP,
    last_success_at       TIMESTAMP,
    last_error            TEXT,
    last_error_at         TIMESTAMP,
    messages_ingested     INTEGER NOT NULL DEFAULT 0
);
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/accountpilot/unit/core/test_db_migrations.py -v`
Expected: 7 passed (3 from Task 2 + 4 from this task).

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/db/migrations/001_init.sql tests/accountpilot/unit/core/test_db_migrations.py
git commit -m "$(cat <<'EOF'
feat(core/db): add 001_init.sql with full 9-table schema

Implement the schema from the design spec: people, identifiers, accounts,
messages, email_details, imessage_details, message_people, attachments,
plus the messages_fts FTS5 virtual table and its triggers, and a
sync_status table for per-account health.

FTS uses a plain (not contentless) FTS5 table for simpler delete/update
semantics. Triggers keep messages_fts.body_text in sync with messages,
and messages_fts.subject in sync with email_details.
EOF
)"
```

---

### Task 4: DB connection helper + tmp_db async fixture

**Files:**
- Create: `src/accountpilot/core/db/connection.py`
- Modify: `tests/accountpilot/conftest.py` (add `tmp_db` async fixture)

The connection helper opens an `aiosqlite.Connection`, sets pragmas (WAL, foreign_keys=ON, busy_timeout), and applies migrations.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_db_connection.py` (new file):
```python
from __future__ import annotations

from pathlib import Path

import aiosqlite

from accountpilot.core.db.connection import open_db


async def test_open_db_applies_migrations_and_sets_pragmas(
    tmp_db_path: Path,
) -> None:
    async with open_db(tmp_db_path) as db:
        async with db.execute("PRAGMA journal_mode") as cur:
            row = await cur.fetchone()
            assert row[0].lower() == "wal"
        async with db.execute("PRAGMA foreign_keys") as cur:
            row = await cur.fetchone()
            assert row[0] == 1
        async with db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='people'"
        ) as cur:
            assert (await cur.fetchone()) is not None


async def test_open_db_idempotent_on_second_open(tmp_db_path: Path) -> None:
    async with open_db(tmp_db_path) as db:
        async with db.execute("SELECT MAX(version) FROM schema_version") as cur:
            v1 = (await cur.fetchone())[0]
    async with open_db(tmp_db_path) as db:
        async with db.execute("SELECT MAX(version) FROM schema_version") as cur:
            v2 = (await cur.fetchone())[0]
    assert v1 == v2
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_db_connection.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `open_db`**

`src/accountpilot/core/db/connection.py`:
```python
"""SQLite connection setup for AccountPilot.

`open_db(path)` is the single entrypoint used by Storage and the CLI to
obtain an aiosqlite.Connection with the right pragmas and an up-to-date
schema. It is an async context manager.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from accountpilot.core.db.migrations import apply_migrations

_MIGRATIONS_DIR = Path(__file__).parent / "migrations"


@asynccontextmanager
async def open_db(path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Open a SQLite DB at `path`, apply pending migrations, yield the connection."""
    path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(path)
    try:
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA busy_timeout = 5000")
        db.row_factory = aiosqlite.Row
        await apply_migrations(db, _MIGRATIONS_DIR)
        yield db
    finally:
        await db.close()
```

- [ ] **Step 4: Add `tmp_db` async fixture**

Append to `tests/accountpilot/conftest.py`:
```python
import aiosqlite  # noqa: E402

from accountpilot.core.db.connection import open_db  # noqa: E402


@pytest.fixture
async def tmp_db(tmp_db_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """Async fixture: opened, migrated SQLite connection at tmp_db_path."""
    async with open_db(tmp_db_path) as db:
        yield db
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/accountpilot/unit/core/ -v`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/accountpilot/core/db/connection.py tests/accountpilot/unit/core/test_db_connection.py tests/accountpilot/conftest.py
git commit -m "$(cat <<'EOF'
feat(core/db): add async open_db helper

Provide a single entrypoint for opening a SQLite DB with the pragmas
AccountPilot expects (WAL, foreign_keys=ON, busy_timeout=5s) and apply
pending migrations. Used by Storage and the CLI.

Add a tmp_db async fixture for tests that need a fully-migrated DB
without setting up pragmas in every test.
EOF
)"
```

---

### Task 5: Pydantic domain models

**Files:**
- Create: `src/accountpilot/core/models.py`
- Test: `tests/accountpilot/unit/core/test_models.py`

Pydantic v2 models for `EmailMessage`, `IMessageMessage`, `AttachmentBlob`, `Identifier`, `SaveResult`, `Direction`, `IdentifierKind`. These are imported by both Storage and plugins.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_models.py`:
```python
from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from accountpilot.core.models import (
    AttachmentBlob,
    EmailMessage,
    IMessageMessage,
    Identifier,
    SaveResult,
)


def test_attachment_blob_requires_filename_and_content() -> None:
    blob = AttachmentBlob(filename="hello.txt", content=b"hi", mime_type="text/plain")
    assert blob.filename == "hello.txt"
    assert blob.content == b"hi"


def test_email_message_minimum_fields() -> None:
    msg = EmailMessage(
        account_id=1,
        external_id="<a@b>",
        sent_at=datetime(2026, 5, 1, 12, 0, 0),
        received_at=None,
        direction="inbound",
        from_address="a@b.com",
        to_addresses=["c@d.com"],
        cc_addresses=[],
        bcc_addresses=[],
        subject="hi",
        body_text="hello",
        body_html=None,
        in_reply_to=None,
        references=[],
        imap_uid=42,
        mailbox="INBOX",
        gmail_thread_id=None,
        labels=[],
        raw_headers={},
        attachments=[],
    )
    assert msg.from_address == "a@b.com"


def test_email_message_rejects_invalid_direction() -> None:
    with pytest.raises(ValidationError):
        EmailMessage(
            account_id=1, external_id="x", sent_at=datetime.now(),
            received_at=None, direction="sideways",  # type: ignore[arg-type]
            from_address="a@b", to_addresses=[], cc_addresses=[],
            bcc_addresses=[], subject="", body_text="", body_html=None,
            in_reply_to=None, references=[], imap_uid=0, mailbox="",
            gmail_thread_id=None, labels=[], raw_headers={}, attachments=[],
        )


def test_imessage_message_minimum_fields() -> None:
    msg = IMessageMessage(
        account_id=1,
        external_id="GUID",
        sent_at=datetime(2026, 5, 1),
        direction="outbound",
        sender_handle="+15551234567",
        chat_guid="chat-1",
        participants=["+15551234567", "+15559876543"],
        body_text="hi",
        service="iMessage",
        is_read=True,
        date_read=None,
        attachments=[],
    )
    assert msg.service == "iMessage"


def test_identifier_kind_constrained() -> None:
    Identifier(kind="email", value="a@b", is_primary=False)
    with pytest.raises(ValidationError):
        Identifier(kind="bogus", value="x", is_primary=False)  # type: ignore[arg-type]


def test_save_result_actions() -> None:
    SaveResult(action="inserted", message_id=1)
    SaveResult(action="skipped", message_id=1)
    SaveResult(action="updated", message_id=1)
    with pytest.raises(ValidationError):
        SaveResult(action="zzz", message_id=1)  # type: ignore[arg-type]
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_models.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement models**

`src/accountpilot/core/models.py`:
```python
"""Pydantic v2 domain models shared between plugins and Storage."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

Direction = Literal["inbound", "outbound"]
IdentifierKind = Literal[
    "email",
    "phone",
    "imessage_handle",
    "telegram_username",
    "whatsapp_number",
]
IMessageService = Literal["iMessage", "SMS"]
SaveAction = Literal["inserted", "skipped", "updated"]
PersonRole = Literal["from", "to", "cc", "bcc", "participant"]


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AttachmentBlob(_StrictBase):
    filename: str
    content: bytes
    mime_type: str | None


class Identifier(_StrictBase):
    kind: IdentifierKind
    value: str
    is_primary: bool = False


class EmailMessage(_StrictBase):
    account_id: int
    external_id: str
    sent_at: datetime
    received_at: datetime | None
    direction: Direction
    from_address: str
    to_addresses: list[str]
    cc_addresses: list[str]
    bcc_addresses: list[str]
    subject: str
    body_text: str
    body_html: str | None
    in_reply_to: str | None
    references: list[str]
    imap_uid: int
    mailbox: str
    gmail_thread_id: str | None
    labels: list[str]
    raw_headers: dict[str, str]
    attachments: list[AttachmentBlob]


class IMessageMessage(_StrictBase):
    account_id: int
    external_id: str
    sent_at: datetime
    direction: Direction
    sender_handle: str
    chat_guid: str
    participants: list[str]
    body_text: str
    service: IMessageService
    is_read: bool
    date_read: datetime | None
    attachments: list[AttachmentBlob]


class SaveResult(_StrictBase):
    action: SaveAction
    message_id: int
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_models.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/models.py tests/accountpilot/unit/core/test_models.py
git commit -m "$(cat <<'EOF'
feat(core): add Pydantic domain models

EmailMessage, IMessageMessage, AttachmentBlob, Identifier, and SaveResult
are the typed contract between plugins and the Storage façade. Models
use frozen=True + extra='forbid' so plugins cannot smuggle unexpected
fields and Storage can rely on the shape.

Constrained-string fields (Direction, IdentifierKind, SaveAction,
IMessageService, PersonRole) are exported as Literal aliases.
EOF
)"
```

---

### Task 6: CAS attachment writer

**Files:**
- Create: `src/accountpilot/core/cas.py`
- Test: `tests/accountpilot/unit/core/test_cas.py`

Content-addressed store: `cas_root/<hash[:2]>/<hash[2:4]>/<hash>.bin`. Writes are atomic (temp file + rename). Idempotent: if hash file already exists, skip write. Returns `(content_hash, cas_path)` where `cas_path` is relative to `cas_root`.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_cas.py`:
```python
from __future__ import annotations

import hashlib
from pathlib import Path

from accountpilot.core.cas import CASStore


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_write_returns_hash_and_relative_path(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    content = b"hello world"
    h, rel = cas.write(content)
    assert h == _sha256(content)
    assert rel == f"{h[:2]}/{h[2:4]}/{h}.bin"
    assert (tmp_runtime / "attachments" / rel).read_bytes() == content


def test_write_is_idempotent(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    content = b"abc"
    h1, rel1 = cas.write(content)
    h2, rel2 = cas.write(content)
    assert h1 == h2
    assert rel1 == rel2
    assert (tmp_runtime / "attachments" / rel1).read_bytes() == content


def test_write_uses_atomic_rename(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    cas.write(b"x")
    # No leftover temp files in the cas root.
    leftover = list((tmp_runtime / "attachments").rglob("*.tmp"))
    assert leftover == []


def test_path_returns_absolute_path(tmp_runtime: Path) -> None:
    cas = CASStore(tmp_runtime / "attachments")
    h, rel = cas.write(b"y")
    assert cas.path(rel) == (tmp_runtime / "attachments" / rel).resolve()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_cas.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement CASStore**

`src/accountpilot/core/cas.py`:
```python
"""Content-addressed store for attachment bytes.

Writes blobs to `<root>/<hash[:2]>/<hash[2:4]>/<hash>.bin` atomically
(temp file + rename) and idempotently (skip if file exists).
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


class CASStore:
    """Filesystem-backed content-addressed blob store."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, content: bytes) -> tuple[str, str]:
        """Write `content` and return (sha256_hex, relative_path_from_root)."""
        h = hashlib.sha256(content).hexdigest()
        rel = f"{h[:2]}/{h[2:4]}/{h}.bin"
        target = self.root / rel
        if target.exists():
            return h, rel

        target.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file in the same directory + os.replace.
        fd, tmp_path = tempfile.mkstemp(
            dir=target.parent, prefix=".cas-", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(content)
            os.replace(tmp_path, target)
        except Exception:
            if Path(tmp_path).exists():
                Path(tmp_path).unlink()
            raise
        return h, rel

    def path(self, relative: str) -> Path:
        """Return absolute path for a CAS-relative path."""
        return (self.root / relative).resolve()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_cas.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/cas.py tests/accountpilot/unit/core/test_cas.py
git commit -m "$(cat <<'EOF'
feat(core): add content-addressed attachment store

CASStore writes blobs to <root>/<h[:2]>/<h[2:4]>/<h>.bin atomically and
idempotently. Used by Storage when persisting attachments. The two-level
fanout keeps directory sizes manageable for typical mailbox volumes.
EOF
)"
```

---

### Task 7: Identity normalization helpers

**Files:**
- Create: `src/accountpilot/core/identity.py` (normalization only this task; resolution + merge in Tasks 8–9)
- Test: `tests/accountpilot/unit/core/test_identity_normalize.py`

Functions: `normalize_email`, `normalize_phone`, `normalize_handle`. `normalize_phone` uses the `phonenumbers` library for E.164 formatting; falls back gracefully on unparseable input.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_identity_normalize.py`:
```python
from __future__ import annotations

import pytest

from accountpilot.core.identity import (
    normalize_email,
    normalize_handle,
    normalize_phone,
)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Foo@Bar.COM", "foo@bar.com"),
        ("  foo@bar.com  ", "foo@bar.com"),
        ("mailto:foo@bar.com", "foo@bar.com"),
        ("MAILTO:Foo@Bar.com", "foo@bar.com"),
    ],
)
def test_normalize_email(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


@pytest.mark.parametrize(
    "raw, default_region, expected",
    [
        ("+90 505 249 01 39", None, "+905052490139"),
        ("905052490139", "TR", "+905052490139"),
        ("05052490139", "TR", "+905052490139"),
        ("+1 (555) 123-4567", None, "+15551234567"),
    ],
)
def test_normalize_phone_e164(
    raw: str, default_region: str | None, expected: str
) -> None:
    assert normalize_phone(raw, default_region=default_region) == expected


def test_normalize_phone_returns_raw_when_unparseable() -> None:
    # Garbage input passes through stripped — never raises.
    assert normalize_phone("nonsense") == "nonsense"


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("+15551234567", "+15551234567"),     # phone-shaped → kept as phone
        ("Foo@Bar.com", "foo@bar.com"),       # email-shaped → lowercased
        (" Foo  ", "foo"),                    # arbitrary handle → lowercased+stripped
    ],
)
def test_normalize_handle_dispatches(raw: str, expected: str) -> None:
    assert normalize_handle(raw) == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_identity_normalize.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement normalization**

`src/accountpilot/core/identity.py` (initial — extended in Tasks 8–9):
```python
"""Identity normalization, find-or-create, and merge logic."""

from __future__ import annotations

import phonenumbers


def normalize_email(raw: str) -> str:
    """Lowercase, strip whitespace, drop a `mailto:` prefix."""
    s = raw.strip()
    if s.lower().startswith("mailto:"):
        s = s[len("mailto:"):]
    return s.strip().lower()


def normalize_phone(raw: str, *, default_region: str | None = None) -> str:
    """Best-effort E.164 normalization. Returns stripped raw if unparseable."""
    s = raw.strip()
    try:
        parsed = phonenumbers.parse(s, default_region)
    except phonenumbers.NumberParseException:
        return s
    if not phonenumbers.is_valid_number(parsed):
        return s
    return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)


def normalize_handle(raw: str) -> str:
    """Dispatch by shape: phone-like → phone E.164; email-like → lowercase email; else lowercase strip."""
    s = raw.strip()
    if "@" in s:
        return normalize_email(s)
    if s.startswith("+") or s.replace(" ", "").replace("-", "").isdigit():
        normalized = normalize_phone(s)
        if normalized != s:
            return normalized
    return s.lower()
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_identity_normalize.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/identity.py tests/accountpilot/unit/core/test_identity_normalize.py
git commit -m "$(cat <<'EOF'
feat(core/identity): add identifier normalization helpers

normalize_email lowercases and strips a mailto: prefix. normalize_phone
uses the phonenumbers library to reach E.164; on unparseable input it
returns the stripped raw value rather than raising. normalize_handle
dispatches by shape so a single helper handles email/phone/free-form
identifiers.
EOF
)"
```

---

### Task 8: Identity find-or-create

**Files:**
- Modify: `src/accountpilot/core/identity.py` (append `find_or_create_person`)
- Test: `tests/accountpilot/unit/core/test_identity_find_or_create.py`

`find_or_create_person(db, kind, value, *, default_name=None)` looks up `(kind, normalized_value)` in `identifiers`. If found, returns the `person_id`. If missing, creates a `people` row with `is_owner=0` and an `identifiers` row, then returns the new id. Pulls a sensible default name from `default_name` (e.g., display-name parsed from `Foo Bar <foo@bar.com>`) or "Unknown" when nothing is given.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_identity_find_or_create.py`:
```python
from __future__ import annotations

import aiosqlite

from accountpilot.core.identity import find_or_create_person


async def test_creates_person_and_identifier(tmp_db: aiosqlite.Connection) -> None:
    pid = await find_or_create_person(
        tmp_db, kind="email", value="Foo@Bar.com", default_name="Foo Bar"
    )
    async with tmp_db.execute(
        "SELECT name, surname, is_owner FROM people WHERE id=?", (pid,)
    ) as cur:
        row = await cur.fetchone()
    assert row["name"] == "Foo"
    assert row["surname"] == "Bar"
    assert row["is_owner"] == 0
    async with tmp_db.execute(
        "SELECT person_id, kind, value FROM identifiers WHERE person_id=?", (pid,)
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "email"
    assert rows[0]["value"] == "foo@bar.com"


async def test_returns_existing_person(tmp_db: aiosqlite.Connection) -> None:
    pid1 = await find_or_create_person(
        tmp_db, kind="email", value="x@y.com", default_name="X"
    )
    pid2 = await find_or_create_person(
        tmp_db, kind="email", value="X@Y.COM", default_name="someone else"
    )
    assert pid1 == pid2


async def test_normalizes_phone_before_lookup(tmp_db: aiosqlite.Connection) -> None:
    pid1 = await find_or_create_person(
        tmp_db, kind="phone", value="+90 505 249 01 39", default_name=None
    )
    pid2 = await find_or_create_person(
        tmp_db, kind="phone", value="905052490139", default_name=None
    )
    assert pid1 == pid2


async def test_default_name_unknown_when_missing(
    tmp_db: aiosqlite.Connection,
) -> None:
    pid = await find_or_create_person(
        tmp_db, kind="email", value="anon@example.com", default_name=None
    )
    async with tmp_db.execute("SELECT name FROM people WHERE id=?", (pid,)) as cur:
        row = await cur.fetchone()
    assert row["name"] == "Unknown"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_identity_find_or_create.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `find_or_create_person` and `_split_display_name`**

Append to `src/accountpilot/core/identity.py`:
```python
from datetime import UTC, datetime

import aiosqlite

# ... existing functions above ...


async def find_or_create_person(
    db: aiosqlite.Connection,
    *,
    kind: str,
    value: str,
    default_name: str | None = None,
) -> int:
    """Look up the identifier; return person_id, creating both rows if absent."""
    if kind == "email":
        normalized = normalize_email(value)
    elif kind == "phone":
        normalized = normalize_phone(value)
    else:
        normalized = normalize_handle(value)

    async with db.execute(
        "SELECT person_id FROM identifiers WHERE kind=? AND value=?",
        (kind, normalized),
    ) as cur:
        row = await cur.fetchone()
    if row is not None:
        return int(row["person_id"])

    name, surname = _split_display_name(default_name)
    now = datetime.now(UTC).isoformat()
    cur2 = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES (?, ?, 0, ?, ?)",
        (name, surname, now, now),
    )
    person_id = cur2.lastrowid
    assert person_id is not None
    await db.execute(
        "INSERT INTO identifiers (person_id, kind, value, is_primary, created_at) "
        "VALUES (?, ?, ?, 0, ?)",
        (person_id, kind, normalized, now),
    )
    await db.commit()
    return person_id


def _split_display_name(name: str | None) -> tuple[str, str | None]:
    """Split 'Foo Bar' → ('Foo', 'Bar'); single token → ('Foo', None); missing → ('Unknown', None)."""
    if not name or not name.strip():
        return "Unknown", None
    parts = name.strip().split(maxsplit=1)
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1]
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_identity_find_or_create.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/identity.py tests/accountpilot/unit/core/test_identity_find_or_create.py
git commit -m "$(cat <<'EOF'
feat(core/identity): add find_or_create_person

Look up an identifier (kind, normalized value); return its person_id, or
create both a people row (is_owner=0) and the identifiers row when no
match exists. Display name parsing splits 'Foo Bar' into name/surname;
missing input falls back to 'Unknown'. Normalization is run inside the
function so callers can pass raw addresses/handles.
EOF
)"
```

---

### Task 9: Identity merge

**Files:**
- Modify: `src/accountpilot/core/identity.py` (append `merge_people`)
- Test: `tests/accountpilot/unit/core/test_identity_merge.py`

`merge_people(db, keep_id, discard_id)` re-points every FK from `discard_id` to `keep_id` and deletes the discarded person. Tables to update: `identifiers`, `accounts.owner_id`, `message_people.person_id`. Runs in a single transaction.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_identity_merge.py`:
```python
from __future__ import annotations

from datetime import datetime

import aiosqlite
import pytest

from accountpilot.core.identity import find_or_create_person, merge_people


async def _seed_owner(db: aiosqlite.Connection, name: str) -> int:
    cur = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES (?, NULL, 1, ?, ?)",
        (name, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    pid = cur.lastrowid
    assert pid is not None
    await db.commit()
    return pid


async def test_merge_repoints_identifiers(tmp_db: aiosqlite.Connection) -> None:
    keep = await find_or_create_person(
        tmp_db, kind="email", value="keep@x.com", default_name="K"
    )
    discard = await find_or_create_person(
        tmp_db, kind="email", value="discard@x.com", default_name="D"
    )
    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute(
        "SELECT person_id FROM identifiers WHERE value=?", ("discard@x.com",)
    ) as cur:
        row = await cur.fetchone()
    assert row["person_id"] == keep


async def test_merge_deletes_discarded_person(tmp_db: aiosqlite.Connection) -> None:
    keep = await find_or_create_person(
        tmp_db, kind="email", value="a@b.com", default_name="A"
    )
    discard = await find_or_create_person(
        tmp_db, kind="email", value="c@d.com", default_name="C"
    )
    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute(
        "SELECT 1 FROM people WHERE id=?", (discard,)
    ) as cur:
        assert (await cur.fetchone()) is None


async def test_merge_repoints_message_people(
    tmp_db: aiosqlite.Connection,
) -> None:
    owner = await _seed_owner(tmp_db, "owner")
    keep = await find_or_create_person(
        tmp_db, kind="email", value="k@x", default_name="K"
    )
    discard = await find_or_create_person(
        tmp_db, kind="email", value="d@x", default_name="D"
    )
    # Minimal account + message so we can attach message_people rows.
    await tmp_db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'gmail', 'a@b.com', 1, ?, ?)",
        (owner, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    await tmp_db.execute(
        "INSERT INTO messages (account_id, source, external_id, sent_at, "
        "body_text, direction, created_at) VALUES (1, 'gmail', 'mid', ?, '', "
        "'inbound', ?)",
        (datetime.now().isoformat(), datetime.now().isoformat()),
    )
    await tmp_db.execute(
        "INSERT INTO message_people (message_id, person_id, role) VALUES (1, ?, 'from')",
        (discard,),
    )
    await tmp_db.commit()

    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute(
        "SELECT person_id FROM message_people WHERE message_id=1"
    ) as cur:
        rows = await cur.fetchall()
    assert [r["person_id"] for r in rows] == [keep]


async def test_merge_repoints_account_owner(tmp_db: aiosqlite.Connection) -> None:
    keep = await _seed_owner(tmp_db, "keeper")
    discard = await _seed_owner(tmp_db, "discarder")
    await tmp_db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'gmail', 'a@b.com', 1, ?, ?)",
        (discard, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    await tmp_db.commit()

    await merge_people(tmp_db, keep_id=keep, discard_id=discard)

    async with tmp_db.execute("SELECT owner_id FROM accounts WHERE id=1") as cur:
        row = await cur.fetchone()
    assert row["owner_id"] == keep


async def test_merge_rejects_self_merge(tmp_db: aiosqlite.Connection) -> None:
    keep = await find_or_create_person(
        tmp_db, kind="email", value="x@y", default_name="X"
    )
    with pytest.raises(ValueError):
        await merge_people(tmp_db, keep_id=keep, discard_id=keep)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_identity_merge.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement merge**

Append to `src/accountpilot/core/identity.py`:
```python
async def merge_people(
    db: aiosqlite.Connection, *, keep_id: int, discard_id: int
) -> None:
    """Re-point all FKs from `discard_id` to `keep_id`, then delete discarded.

    Single transaction. Self-merge raises ValueError.
    """
    if keep_id == discard_id:
        raise ValueError("cannot merge a person with themselves")

    await db.execute("BEGIN")
    try:
        await db.execute(
            "UPDATE identifiers SET person_id=? WHERE person_id=?",
            (keep_id, discard_id),
        )
        await db.execute(
            "UPDATE accounts SET owner_id=? WHERE owner_id=?",
            (keep_id, discard_id),
        )
        # message_people PK is (message_id, person_id, role); duplicates after
        # repointing are silently skipped via INSERT OR IGNORE.
        await db.execute(
            "INSERT OR IGNORE INTO message_people (message_id, person_id, role) "
            "SELECT message_id, ?, role FROM message_people WHERE person_id=?",
            (keep_id, discard_id),
        )
        await db.execute(
            "DELETE FROM message_people WHERE person_id=?", (discard_id,)
        )
        await db.execute("DELETE FROM people WHERE id=?", (discard_id,))
        await db.execute("COMMIT")
    except Exception:
        await db.execute("ROLLBACK")
        raise
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_identity_merge.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/identity.py tests/accountpilot/unit/core/test_identity_merge.py
git commit -m "$(cat <<'EOF'
feat(core/identity): add merge_people

Re-point identifiers, account ownership, and message_people from the
discarded person to the kept person, then delete the discarded row. The
message_people PK collision case is handled via INSERT OR IGNORE so
merging two senders of the same message stays idempotent. Single
transaction; self-merge raises ValueError.
EOF
)"
```

---

### Task 10: `Storage.save_email`

**Files:**
- Create: `src/accountpilot/core/storage.py`
- Test: `tests/accountpilot/unit/core/test_storage_save_email.py`

`Storage` is the sole writer to the DB and CAS. This task implements the constructor, the `save_email` method, and the dedup check. Helpers (`upsert_owner`, `upsert_account`, `latest_*`) come in Task 12; `save_imessage` in Task 11.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_storage_save_email.py`:
```python
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import aiosqlite
import pytest

from accountpilot.core.cas import CASStore
from accountpilot.core.models import AttachmentBlob, EmailMessage
from accountpilot.core.storage import Storage


async def _seed_owner_and_account(db: aiosqlite.Connection) -> tuple[int, int]:
    cur = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES ('Aren', 'E', 1, ?, ?)",
        (datetime.now().isoformat(), datetime.now().isoformat()),
    )
    owner_id = cur.lastrowid
    cur = await db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'gmail', 'a@b.com', 1, ?, ?)",
        (owner_id, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    account_id = cur.lastrowid
    await db.commit()
    return owner_id, account_id


def _make_email(account_id: int, **overrides) -> EmailMessage:
    base = dict(
        account_id=account_id,
        external_id="<msg-1@x>",
        sent_at=datetime(2026, 5, 1, 10, 0),
        received_at=datetime(2026, 5, 1, 10, 0, 5),
        direction="inbound",
        from_address="Foo Bar <foo@bar.com>",
        to_addresses=["aren@a.com"],
        cc_addresses=[],
        bcc_addresses=[],
        subject="Hello",
        body_text="Body text body text",
        body_html=None,
        in_reply_to=None,
        references=[],
        imap_uid=42,
        mailbox="INBOX",
        gmail_thread_id=None,
        labels=["INBOX"],
        raw_headers={"Subject": "Hello"},
        attachments=[],
    )
    base.update(overrides)
    return EmailMessage(**base)


async def test_save_email_inserts_message_and_resolves_people(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    result = await storage.save_email(_make_email(account_id))
    assert result.action == "inserted"

    async with tmp_db.execute(
        "SELECT subject FROM email_details WHERE message_id=?", (result.message_id,)
    ) as cur:
        assert (await cur.fetchone())["subject"] == "Hello"

    async with tmp_db.execute(
        "SELECT p.name, mp.role FROM message_people mp JOIN people p ON p.id=mp.person_id "
        "WHERE mp.message_id=? ORDER BY mp.role", (result.message_id,)
    ) as cur:
        rows = [(r["name"], r["role"]) for r in await cur.fetchall()]
    # One 'from' (Foo) and one 'to' (Unknown — aren@a.com had no display name).
    assert ("Foo", "from") in rows
    assert any(role == "to" for _, role in rows)


async def test_save_email_dedup_returns_skipped(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_email(account_id)
    r1 = await storage.save_email(msg)
    r2 = await storage.save_email(msg)
    assert r1.action == "inserted"
    assert r2.action == "skipped"
    assert r2.message_id == r1.message_id

    async with tmp_db.execute("SELECT COUNT(*) FROM messages") as cur:
        assert (await cur.fetchone())[0] == 1


async def test_save_email_writes_attachments_to_cas_and_attachments_table(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_email(
        account_id,
        attachments=[
            AttachmentBlob(filename="hi.txt", content=b"hello", mime_type="text/plain")
        ],
    )
    result = await storage.save_email(msg)
    async with tmp_db.execute(
        "SELECT filename, content_hash, cas_path, size_bytes "
        "FROM attachments WHERE message_id=?", (result.message_id,)
    ) as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    row = rows[0]
    assert row["filename"] == "hi.txt"
    assert row["size_bytes"] == 5
    assert (tmp_runtime / "attachments" / row["cas_path"]).read_bytes() == b"hello"


async def test_save_email_persists_email_details_json_columns(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_email(
        account_id,
        labels=["INBOX", "IMPORTANT"],
        references=["<a@x>", "<b@x>"],
        raw_headers={"Subject": "Hello", "From": "foo@bar"},
    )
    result = await storage.save_email(msg)
    async with tmp_db.execute(
        "SELECT labels_json, references_json, raw_headers_json "
        "FROM email_details WHERE message_id=?", (result.message_id,)
    ) as cur:
        row = await cur.fetchone()
    assert json.loads(row["labels_json"]) == ["INBOX", "IMPORTANT"]
    assert json.loads(row["references_json"]) == ["<a@x>", "<b@x>"]
    assert json.loads(row["raw_headers_json"]) == {
        "Subject": "Hello", "From": "foo@bar",
    }


async def test_save_email_fts_row_searchable(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    _, account_id = await _seed_owner_and_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    await storage.save_email(_make_email(account_id, body_text="lorem ipsum dolor"))
    async with tmp_db.execute(
        "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'lorem'"
    ) as cur:
        assert (await cur.fetchone()) is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_storage_save_email.py -v`
Expected: ImportError on `accountpilot.core.storage`.

- [ ] **Step 3: Implement Storage and `save_email`**

`src/accountpilot/core/storage.py`:
```python
"""Storage façade — the sole writer to the SQLite DB and CAS attachment store."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import aiosqlite

from accountpilot.core.cas import CASStore
from accountpilot.core.identity import find_or_create_person
from accountpilot.core.models import (
    AttachmentBlob,
    EmailMessage,
    IMessageMessage,
    SaveResult,
)

# Match "Display Name <addr@host>" or bare "addr@host".
_RFC822_ADDR_RE = re.compile(r"^\s*(?:\"?(?P<name>[^<\"]*?)\"?\s*)?<?(?P<addr>[^<>\s]+@[^<>\s]+)>?\s*$")


def _split_address(raw: str) -> tuple[str, str | None]:
    """Return (email_address, display_name_or_None)."""
    m = _RFC822_ADDR_RE.match(raw)
    if m is None:
        return raw.strip(), None
    addr = m.group("addr").strip()
    name = (m.group("name") or "").strip() or None
    return addr, name


class Storage:
    """Sole writer to the AccountPilot DB and CAS."""

    def __init__(self, db: aiosqlite.Connection, cas: CASStore) -> None:
        self.db = db
        self.cas = cas

    async def save_email(self, msg: EmailMessage) -> SaveResult:
        # 1. CAS writes happen outside the DB transaction. Idempotent.
        cas_entries: list[tuple[AttachmentBlob, str, str]] = []
        for blob in msg.attachments:
            content_hash, cas_rel = self.cas.write(blob.content)
            cas_entries.append((blob, content_hash, cas_rel))

        # 2. DB transaction.
        await self.db.execute("BEGIN")
        try:
            # Dedup.
            async with self.db.execute(
                "SELECT id FROM messages WHERE account_id=? AND external_id=?",
                (msg.account_id, msg.external_id),
            ) as cur:
                existing = await cur.fetchone()
            if existing is not None:
                await self.db.execute("ROLLBACK")
                return SaveResult(action="skipped", message_id=int(existing["id"]))

            # Insert message.
            now = datetime.now(UTC).isoformat()
            cur2 = await self.db.execute(
                "INSERT INTO messages (account_id, source, external_id, thread_id, "
                "sent_at, received_at, body_text, body_html, direction, created_at) "
                "VALUES (?, 'gmail', ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg.account_id,
                    msg.external_id,
                    msg.gmail_thread_id,
                    msg.sent_at.isoformat(),
                    msg.received_at.isoformat() if msg.received_at else None,
                    msg.body_text,
                    msg.body_html,
                    msg.direction,
                    now,
                ),
            )
            message_id = cur2.lastrowid
            assert message_id is not None

            # email_details.
            await self.db.execute(
                "INSERT INTO email_details (message_id, subject, in_reply_to, "
                "references_json, imap_uid, mailbox, gmail_thread_id, labels_json, "
                "raw_headers_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    msg.subject,
                    msg.in_reply_to,
                    json.dumps(msg.references),
                    msg.imap_uid,
                    msg.mailbox,
                    msg.gmail_thread_id,
                    json.dumps(msg.labels),
                    json.dumps(msg.raw_headers),
                ),
            )

            # message_people.
            for raw, role in self._email_address_roles(msg):
                addr, display = _split_address(raw)
                pid = await find_or_create_person(
                    self.db, kind="email", value=addr, default_name=display
                )
                await self.db.execute(
                    "INSERT OR IGNORE INTO message_people (message_id, person_id, role) "
                    "VALUES (?, ?, ?)",
                    (message_id, pid, role),
                )

            # attachments.
            for blob, content_hash, cas_rel in cas_entries:
                await self.db.execute(
                    "INSERT INTO attachments (message_id, filename, content_hash, "
                    "mime_type, size_bytes, cas_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        message_id,
                        blob.filename,
                        content_hash,
                        blob.mime_type,
                        len(blob.content),
                        cas_rel,
                    ),
                )

            await self.db.execute("COMMIT")
            return SaveResult(action="inserted", message_id=message_id)
        except Exception:
            await self.db.execute("ROLLBACK")
            raise

    @staticmethod
    def _email_address_roles(msg: EmailMessage) -> list[tuple[str, str]]:
        roles: list[tuple[str, str]] = [(msg.from_address, "from")]
        for a in msg.to_addresses:
            roles.append((a, "to"))
        for a in msg.cc_addresses:
            roles.append((a, "cc"))
        for a in msg.bcc_addresses:
            roles.append((a, "bcc"))
        return roles
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_storage_save_email.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/storage.py tests/accountpilot/unit/core/test_storage_save_email.py
git commit -m "$(cat <<'EOF'
feat(core/storage): add Storage.save_email

Implement the email branch of the Storage façade: write attachments to
CAS first (idempotent, outside the DB transaction), then insert into
messages + email_details + message_people + attachments inside one DB
transaction with dedup on (account_id, external_id). RFC822-style
'Display Name <addr>' senders are split so display names feed into
find_or_create_person as default name hints.

CAS write happens before the DB transaction so a transaction rollback
leaves at most an unreferenced CAS file (harmless, content-addressed).
EOF
)"
```

---

### Task 11: `Storage.save_imessage`

**Files:**
- Modify: `src/accountpilot/core/storage.py`
- Test: `tests/accountpilot/unit/core/test_storage_save_imessage.py`

Same shape as `save_email` but writes to `imessage_details` and uses `imessage_handle` as the identifier kind. Sender + each unique participant become `message_people` rows (sender = `from`, others = `participant`).

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_storage_save_imessage.py`:
```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import aiosqlite

from accountpilot.core.cas import CASStore
from accountpilot.core.models import AttachmentBlob, IMessageMessage
from accountpilot.core.storage import Storage


async def _seed_imessage_account(db: aiosqlite.Connection) -> int:
    cur = await db.execute(
        "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
        "VALUES ('Aren', 'E', 1, ?, ?)",
        (datetime.now().isoformat(), datetime.now().isoformat()),
    )
    owner_id = cur.lastrowid
    cur = await db.execute(
        "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
        "created_at, updated_at) VALUES (?, 'imessage', '+15551234567', 1, ?, ?)",
        (owner_id, datetime.now().isoformat(), datetime.now().isoformat()),
    )
    await db.commit()
    return cur.lastrowid


def _make_imessage(account_id: int, **overrides) -> IMessageMessage:
    base = dict(
        account_id=account_id,
        external_id="GUID-1",
        sent_at=datetime(2026, 5, 1, 10, 0),
        direction="inbound",
        sender_handle="+1 (555) 987-6543",
        chat_guid="chat-1",
        participants=["+15551234567", "+15559876543"],
        body_text="hi from imessage",
        service="iMessage",
        is_read=True,
        date_read=None,
        attachments=[],
    )
    base.update(overrides)
    return IMessageMessage(**base)


async def test_save_imessage_inserts_message_and_details(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    result = await storage.save_imessage(_make_imessage(account_id))
    assert result.action == "inserted"

    async with tmp_db.execute(
        "SELECT chat_guid, service FROM imessage_details WHERE message_id=?",
        (result.message_id,),
    ) as cur:
        row = await cur.fetchone()
    assert row["chat_guid"] == "chat-1"
    assert row["service"] == "iMessage"


async def test_save_imessage_resolves_sender_and_participants(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    result = await storage.save_imessage(_make_imessage(account_id))
    async with tmp_db.execute(
        "SELECT role FROM message_people WHERE message_id=? ORDER BY role",
        (result.message_id,),
    ) as cur:
        rows = [r["role"] for r in await cur.fetchall()]
    assert "from" in rows
    assert "participant" in rows


async def test_save_imessage_dedup(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_imessage(account_id)
    r1 = await storage.save_imessage(msg)
    r2 = await storage.save_imessage(msg)
    assert r1.action == "inserted"
    assert r2.action == "skipped"


async def test_save_imessage_attachment(
    tmp_db: aiosqlite.Connection, tmp_runtime: Path
) -> None:
    account_id = await _seed_imessage_account(tmp_db)
    storage = Storage(tmp_db, CASStore(tmp_runtime / "attachments"))
    msg = _make_imessage(
        account_id,
        attachments=[
            AttachmentBlob(filename="pic.jpg", content=b"\xff\xd8\xff", mime_type="image/jpeg")
        ],
    )
    result = await storage.save_imessage(msg)
    async with tmp_db.execute(
        "SELECT cas_path FROM attachments WHERE message_id=?", (result.message_id,)
    ) as cur:
        row = await cur.fetchone()
    assert (tmp_runtime / "attachments" / row["cas_path"]).read_bytes() == b"\xff\xd8\xff"
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_storage_save_imessage.py -v`
Expected: AttributeError on `Storage.save_imessage`.

- [ ] **Step 3: Implement `save_imessage`**

Append to `Storage` in `src/accountpilot/core/storage.py`:
```python
    async def save_imessage(self, msg: IMessageMessage) -> SaveResult:
        cas_entries: list[tuple[AttachmentBlob, str, str]] = []
        for blob in msg.attachments:
            content_hash, cas_rel = self.cas.write(blob.content)
            cas_entries.append((blob, content_hash, cas_rel))

        await self.db.execute("BEGIN")
        try:
            async with self.db.execute(
                "SELECT id FROM messages WHERE account_id=? AND external_id=?",
                (msg.account_id, msg.external_id),
            ) as cur:
                existing = await cur.fetchone()
            if existing is not None:
                await self.db.execute("ROLLBACK")
                return SaveResult(action="skipped", message_id=int(existing["id"]))

            now = datetime.now(UTC).isoformat()
            cur2 = await self.db.execute(
                "INSERT INTO messages (account_id, source, external_id, thread_id, "
                "sent_at, body_text, direction, created_at) "
                "VALUES (?, 'imessage', ?, ?, ?, ?, ?, ?)",
                (
                    msg.account_id,
                    msg.external_id,
                    msg.chat_guid,
                    msg.sent_at.isoformat(),
                    msg.body_text,
                    msg.direction,
                    now,
                ),
            )
            message_id = cur2.lastrowid
            assert message_id is not None

            await self.db.execute(
                "INSERT INTO imessage_details (message_id, chat_guid, service, "
                "is_from_me, is_read, date_read) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    message_id,
                    msg.chat_guid,
                    msg.service,
                    1 if msg.direction == "outbound" else 0,
                    1 if msg.is_read else 0,
                    msg.date_read.isoformat() if msg.date_read else None,
                ),
            )

            sender_pid = await find_or_create_person(
                self.db, kind="imessage_handle", value=msg.sender_handle,
                default_name=None,
            )
            await self.db.execute(
                "INSERT OR IGNORE INTO message_people (message_id, person_id, role) "
                "VALUES (?, ?, 'from')",
                (message_id, sender_pid),
            )
            for handle in msg.participants:
                pid = await find_or_create_person(
                    self.db, kind="imessage_handle", value=handle, default_name=None
                )
                await self.db.execute(
                    "INSERT OR IGNORE INTO message_people (message_id, person_id, role) "
                    "VALUES (?, ?, 'participant')",
                    (message_id, pid),
                )

            for blob, content_hash, cas_rel in cas_entries:
                await self.db.execute(
                    "INSERT INTO attachments (message_id, filename, content_hash, "
                    "mime_type, size_bytes, cas_path) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        message_id, blob.filename, content_hash, blob.mime_type,
                        len(blob.content), cas_rel,
                    ),
                )

            await self.db.execute("COMMIT")
            return SaveResult(action="inserted", message_id=message_id)
        except Exception:
            await self.db.execute("ROLLBACK")
            raise
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_storage_save_imessage.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/storage.py tests/accountpilot/unit/core/test_storage_save_imessage.py
git commit -m "$(cat <<'EOF'
feat(core/storage): add Storage.save_imessage

Mirror save_email for the iMessage source. Sender becomes a 'from' role;
each participant becomes a 'participant' role. Note that the iMessage
identifier kind is 'imessage_handle' so cross-source identity (a phone
that's already in identifiers as kind='phone' from a Gmail correspondent)
won't auto-link until SP3's identifier-kind unification work — for now,
the identifier rows are kept separate by kind.
EOF
)"
```

---

### Task 12: Storage helpers — owners, accounts, latest, batch

**Files:**
- Modify: `src/accountpilot/core/storage.py`
- Test: `tests/accountpilot/unit/core/test_storage_helpers.py`

Adds: `upsert_owner`, `upsert_account`, `latest_external_id`, `latest_sent_at`. Skips the `batch` context manager — defer to the first plugin that needs it (YAGNI).

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_storage_helpers.py`:
```python
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import aiosqlite

from accountpilot.core.cas import CASStore
from accountpilot.core.models import EmailMessage, Identifier
from accountpilot.core.storage import Storage


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
        assert (await cur.fetchone())["is_owner"] == 1


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

    await storage.save_email(_email("a", datetime(2026, 5, 1)))
    await storage.save_email(_email("b", datetime(2026, 5, 2)))
    assert await storage.latest_external_id(account_id) == "b"
    assert await storage.latest_sent_at(account_id) == datetime(2026, 5, 2)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_storage_helpers.py -v`
Expected: AttributeError.

- [ ] **Step 3: Implement helpers**

Append to `Storage` in `src/accountpilot/core/storage.py`:
```python
    # ─── Owner / account upsert ──────────────────────────────────────────

    async def upsert_owner(
        self,
        *,
        name: str,
        surname: str | None,
        identifiers: list[Identifier],
    ) -> int:
        """Find or create an owner. Existence is determined by ANY of the identifiers.

        If multiple identifiers already point to different existing people, returns
        the first match (callers can run merge_people afterwards).
        """
        from accountpilot.core.identity import find_or_create_person

        for ident in identifiers:
            async with self.db.execute(
                "SELECT person_id FROM identifiers WHERE kind=? AND value=?",
                (ident.kind, _normalize_for_kind(ident.kind, ident.value)),
            ) as cur:
                row = await cur.fetchone()
            if row is not None:
                # Promote to owner if not already.
                pid = int(row["person_id"])
                await self.db.execute(
                    "UPDATE people SET is_owner=1, name=?, surname=?, updated_at=? "
                    "WHERE id=?",
                    (name, surname, datetime.now(UTC).isoformat(), pid),
                )
                # Add any new identifiers.
                for missing in identifiers:
                    await find_or_create_person(
                        self.db, kind=missing.kind, value=missing.value,
                        default_name=f"{name} {surname or ''}".strip(),
                    )
                # Re-point any newly-created people to this one if possible.
                # For SP0 we keep this simple: just return pid.
                await self.db.commit()
                return pid

        # No matches — create a new owner row + all identifiers.
        now = datetime.now(UTC).isoformat()
        cur2 = await self.db.execute(
            "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, ?)",
            (name, surname, now, now),
        )
        pid = cur2.lastrowid
        assert pid is not None
        for ident in identifiers:
            await self.db.execute(
                "INSERT INTO identifiers (person_id, kind, value, is_primary, created_at) "
                "VALUES (?, ?, ?, 0, ?)",
                (pid, ident.kind, _normalize_for_kind(ident.kind, ident.value), now),
            )
        await self.db.commit()
        return pid

    async def upsert_account(
        self,
        *,
        source: str,
        identifier: str,
        owner_id: int,
        credentials_ref: str | None = None,
        display_name: str | None = None,
    ) -> int:
        """Find or create an account row. Idempotent on (source, identifier)."""
        async with self.db.execute(
            "SELECT id FROM accounts WHERE source=? AND account_identifier=?",
            (source, identifier),
        ) as cur:
            row = await cur.fetchone()
        if row is not None:
            return int(row["id"])
        now = datetime.now(UTC).isoformat()
        cur2 = await self.db.execute(
            "INSERT INTO accounts (owner_id, source, account_identifier, "
            "display_name, credentials_ref, enabled, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (owner_id, source, identifier, display_name, credentials_ref, now, now),
        )
        await self.db.commit()
        aid = cur2.lastrowid
        assert aid is not None
        return aid

    # ─── Read helpers ────────────────────────────────────────────────────

    async def latest_external_id(self, account_id: int) -> str | None:
        async with self.db.execute(
            "SELECT external_id FROM messages WHERE account_id=? "
            "ORDER BY sent_at DESC, id DESC LIMIT 1",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
        return None if row is None else str(row["external_id"])

    async def latest_sent_at(self, account_id: int) -> datetime | None:
        async with self.db.execute(
            "SELECT MAX(sent_at) AS s FROM messages WHERE account_id=?",
            (account_id,),
        ) as cur:
            row = await cur.fetchone()
        if row is None or row["s"] is None:
            return None
        return datetime.fromisoformat(str(row["s"]))


def _normalize_for_kind(kind: str, value: str) -> str:
    from accountpilot.core.identity import (
        normalize_email,
        normalize_handle,
        normalize_phone,
    )
    if kind == "email":
        return normalize_email(value)
    if kind == "phone":
        return normalize_phone(value)
    return normalize_handle(value)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_storage_helpers.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/storage.py tests/accountpilot/unit/core/test_storage_helpers.py
git commit -m "$(cat <<'EOF'
feat(core/storage): add upsert_owner/account + latest_* helpers

upsert_owner finds an existing person by ANY supplied identifier and
promotes them to owner; otherwise creates a new owner row and registers
all identifiers. upsert_account is idempotent on (source, identifier).
latest_external_id and latest_sent_at let plugins resume backfill/sync
without exposing arbitrary SQL.
EOF
)"
```

---

### Task 13: Plugin base class + entry-point discovery

**Files:**
- Create: `src/accountpilot/core/plugin.py`
- Create: `src/accountpilot/core/auth.py` (stub `Secrets` interface)
- Test: `tests/accountpilot/unit/core/test_plugin_base.py`

Defines `AccountPilotPlugin` ABC with the 5 hooks + optional `cli()`. `discover_plugins()` reads the `accountpilot.plugins` entry-point group. `Secrets` is a thin stub returning `None` for all keys in SP0; SP1 wires up `password_cmd` + 1Password.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_plugin_base.py`:
```python
from __future__ import annotations

from datetime import datetime
from typing import ClassVar

import pytest

from accountpilot.core.auth import Secrets
from accountpilot.core.plugin import AccountPilotPlugin


class _Dummy(AccountPilotPlugin):
    name: ClassVar[str] = "dummy"
    setup_called = False

    async def setup(self) -> None:
        type(self).setup_called = True

    async def backfill(self, account_id: int, *, since: datetime | None = None) -> None:
        return None

    async def sync_once(self, account_id: int) -> None:
        return None

    async def daemon(self, account_id: int) -> None:
        return None

    async def teardown(self) -> None:
        return None


async def test_plugin_subclass_with_all_hooks_instantiable() -> None:
    p = _Dummy(config={}, storage=None, secrets=Secrets({}))  # type: ignore[arg-type]
    await p.setup()
    assert _Dummy.setup_called is True


def test_plugin_must_implement_all_abstract_methods() -> None:
    class _Incomplete(AccountPilotPlugin):
        name = "incomplete"

    with pytest.raises(TypeError):
        _Incomplete(config={}, storage=None, secrets=Secrets({}))  # type: ignore[arg-type,abstract]


def test_secrets_get_returns_none_when_missing() -> None:
    s = Secrets({"a": "b"})
    assert s.get("a") == "b"
    assert s.get("missing") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_plugin_base.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement Secrets stub and AccountPilotPlugin**

`src/accountpilot/core/auth.py`:
```python
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
```

`src/accountpilot/core/plugin.py`:
```python
"""AccountPilot plugin base class and entry-point discovery."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from importlib.metadata import entry_points
from typing import Any, ClassVar

import click

from accountpilot.core.auth import Secrets


class AccountPilotPlugin(ABC):
    """Base class for AccountPilot plugins.

    A plugin handles one source (mail, imessage, ...). All accounts of that
    source are managed by a single plugin instance.
    """

    name: ClassVar[str]

    def __init__(
        self, config: dict[str, Any], storage: Any, secrets: Secrets
    ) -> None:
        self.config = config
        self.storage = storage
        self.secrets = secrets

    @abstractmethod
    async def setup(self) -> None: ...

    @abstractmethod
    async def backfill(
        self, account_id: int, *, since: datetime | None = None
    ) -> None: ...

    @abstractmethod
    async def sync_once(self, account_id: int) -> None: ...

    @abstractmethod
    async def daemon(self, account_id: int) -> None: ...

    @abstractmethod
    async def teardown(self) -> None: ...

    def cli(self) -> click.Group | None:
        return None


def discover_plugins() -> dict[str, type[AccountPilotPlugin]]:
    """Read `accountpilot.plugins` entry points and return name -> class map."""
    found: dict[str, type[AccountPilotPlugin]] = {}
    for ep in entry_points(group="accountpilot.plugins"):
        cls = ep.load()
        if not (isinstance(cls, type) and issubclass(cls, AccountPilotPlugin)):
            continue
        found[ep.name] = cls
    return found
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_plugin_base.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/plugin.py src/accountpilot/core/auth.py tests/accountpilot/unit/core/test_plugin_base.py
git commit -m "$(cat <<'EOF'
feat(core): add AccountPilotPlugin base class + Secrets stub

Define the 5-hook plugin contract (setup, backfill, sync_once, daemon,
teardown) and an optional cli() for plugin-contributed Click subcommands.
discover_plugins() reads the accountpilot.plugins entry-point group.

Secrets is a thin dict wrapper for SP0; SP1 replaces it with a real
password_cmd + 1Password resolver.
EOF
)"
```

---

### Task 14: Config loader

**Files:**
- Create: `src/accountpilot/core/config.py`
- Test: `tests/accountpilot/unit/core/test_config.py`

Defines Pydantic models matching `config.yaml` shape and a `load_config(path)` function with helpful errors.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/core/test_config.py`:
```python
from __future__ import annotations

from pathlib import Path

import pytest

from accountpilot.core.config import Config, load_config


def test_load_minimum_valid_config(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
version: 1
owners:
  - name: Aren
    surname: Eren
    identifiers:
      - { kind: email, value: aren@x.com }
plugins: {}
""")
    cfg = load_config(cfg_path)
    assert isinstance(cfg, Config)
    assert cfg.owners[0].name == "Aren"
    assert cfg.owners[0].identifiers[0].kind == "email"


def test_load_with_plugins(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
version: 1
owners:
  - name: Aren
    surname: null
    identifiers:
      - { kind: email, value: a@b.com }
plugins:
  mail:
    enabled: true
    accounts:
      - identifier: a@b.com
        owner: a@b.com
        provider: gmail
        credentials_ref: "op://x/y/z"
""")
    cfg = load_config(cfg_path)
    assert cfg.plugins["mail"].enabled is True
    assert cfg.plugins["mail"].accounts[0].provider == "gmail"


def test_invalid_version_rejected(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("version: 99\nowners: []\nplugins: {}\n")
    with pytest.raises(ValueError):
        load_config(cfg_path)


def test_unknown_identifier_kind_rejected(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("""
version: 1
owners:
  - name: A
    surname: null
    identifiers:
      - { kind: bogus, value: x }
plugins: {}
""")
    with pytest.raises(ValueError):
        load_config(cfg_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/core/test_config.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement config loader**

`src/accountpilot/core/config.py`:
```python
"""YAML config loader with Pydantic validation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from accountpilot.core.models import IdentifierKind


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentifierEntry(_StrictBase):
    kind: IdentifierKind
    value: str


class OwnerEntry(_StrictBase):
    name: str
    surname: str | None = None
    identifiers: list[IdentifierEntry]


class AccountEntry(_StrictBase):
    identifier: str
    owner: str
    provider: Literal["gmail", "outlook", "imap-generic"] | None = None
    credentials_ref: str | None = None
    chat_db_path: str | None = None  # iMessage-specific


class PluginConfig(_StrictBase):
    enabled: bool = True
    accounts: list[AccountEntry] = []
    # Open dict for plugin-specific tunables (idle_timeout_seconds, etc.).
    extra: dict[str, Any] = {}


class Config(_StrictBase):
    version: Literal[1]
    owners: list[OwnerEntry]
    plugins: dict[str, PluginConfig] = {}


def load_config(path: Path) -> Config:
    raw = yaml.safe_load(path.read_text())
    try:
        return Config.model_validate(raw)
    except ValidationError as e:
        raise ValueError(f"invalid config at {path}: {e}") from e
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/core/test_config.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/config.py tests/accountpilot/unit/core/test_config.py
git commit -m "$(cat <<'EOF'
feat(core): add YAML config loader with Pydantic validation

Define the typed Config + OwnerEntry + AccountEntry + PluginConfig models
matching the design spec's config.yaml shape. load_config raises ValueError
with the file path and the underlying validation message on any schema
mismatch.
EOF
)"
```

---

### Task 15: CLI scaffolding + `db` commands

**Files:**
- Create: `src/accountpilot/core/cli/db_cmds.py`
- Modify: `src/accountpilot/cli.py` (register db group)
- Test: `tests/accountpilot/unit/cli/test_db_cmds.py`

Adds `accountpilot db migrate` (apply pending migrations) and `accountpilot db vacuum` (run `VACUUM`). Both take `--db-path` so tests can target a temp DB.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/cli/test_db_cmds.py`:
```python
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli


def test_db_migrate_creates_db_and_runs(tmp_db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["db", "migrate", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0, result.output
    assert tmp_db_path.exists()


def test_db_vacuum_runs(tmp_db_path: Path) -> None:
    runner = CliRunner()
    runner.invoke(cli, ["db", "migrate", "--db-path", str(tmp_db_path)])
    result = runner.invoke(cli, ["db", "vacuum", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0, result.output
```

`tests/accountpilot/unit/cli/__init__.py`: empty.

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/cli/test_db_cmds.py -v`
Expected: failure on missing `db` subcommand.

- [ ] **Step 3: Implement db commands**

`src/accountpilot/core/cli/db_cmds.py`:
```python
"""accountpilot db ..."""

from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite
import click

from accountpilot.core.db.connection import open_db


@click.group("db")
def db_group() -> None:
    """Database management commands."""


@db_group.command("migrate")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def migrate(db_path: Path) -> None:
    """Apply pending migrations."""

    async def _run() -> None:
        async with open_db(db_path):
            pass  # open_db applies migrations.
        click.echo(f"migrated: {db_path}")

    asyncio.run(_run())


@db_group.command("vacuum")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def vacuum(db_path: Path) -> None:
    """Run SQLite VACUUM on the DB."""

    async def _run() -> None:
        async with aiosqlite.connect(db_path) as db:
            await db.execute("VACUUM")
        click.echo(f"vacuumed: {db_path}")

    asyncio.run(_run())
```

Modify `src/accountpilot/cli.py` to register the `db` group:
```python
"""AccountPilot CLI root."""

import click

from accountpilot.core.cli.db_cmds import db_group


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


cli.add_command(db_group)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/cli/test_db_cmds.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/cli/db_cmds.py src/accountpilot/cli.py tests/accountpilot/unit/cli/
git commit -m "$(cat <<'EOF'
feat(cli): add accountpilot db {migrate,vacuum}

Wire the Click root, register the db subgroup, and add migrate/vacuum
commands that target ~/runtime/accountpilot/accountpilot.db by default
and accept --db-path for tests and ad-hoc use. open_db applies pending
migrations transparently, so `db migrate` only needs to open and close.
EOF
)"
```

---

### Task 16: CLI `search` command

**Files:**
- Create: `src/accountpilot/core/cli/search_cmd.py`
- Modify: `src/accountpilot/cli.py` (register `search`)
- Test: `tests/accountpilot/unit/cli/test_search_cmd.py`

Runs an FTS5 query against `messages_fts` and prints top N (id, sent_at, subject-or-snippet, source).

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/cli/test_search_cmd.py`:
```python
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.cas import CASStore
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import EmailMessage
from accountpilot.core.storage import Storage


def _seed_one_email(db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
                "VALUES ('Aren', NULL, 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            await db.execute(
                "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
                "created_at, updated_at) VALUES (1, 'gmail', 'a@b.com', 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            await db.commit()
            storage = Storage(db, CASStore(db_path.parent / "attachments"))
            await storage.save_email(EmailMessage(
                account_id=1, external_id="m1",
                sent_at=datetime(2026, 5, 1), received_at=None,
                direction="inbound", from_address="z@z",
                to_addresses=[], cc_addresses=[], bcc_addresses=[],
                subject="Project update", body_text="lorem ipsum",
                body_html=None, in_reply_to=None, references=[],
                imap_uid=1, mailbox="INBOX", gmail_thread_id=None,
                labels=[], raw_headers={}, attachments=[],
            ))
    asyncio.run(_run())


def test_search_returns_matching_message(tmp_db_path: Path) -> None:
    _seed_one_email(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["search", "lorem", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0, result.output
    assert "Project update" in result.output


def test_search_no_matches(tmp_db_path: Path) -> None:
    _seed_one_email(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["search", "xyzzy", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0
    assert "no matches" in result.output.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/cli/test_search_cmd.py -v`
Expected: failure on missing `search` command.

- [ ] **Step 3: Implement**

`src/accountpilot/core/cli/search_cmd.py`:
```python
"""accountpilot search <query>"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from accountpilot.core.db.connection import open_db


@click.command("search")
@click.argument("query")
@click.option("--limit", type=int, default=20)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def search_cmd(query: str, limit: int, db_path: Path) -> None:
    """Full-text search over messages."""

    async def _run() -> None:
        async with open_db(db_path) as db:
            async with db.execute(
                """
                SELECT m.id, m.source, m.sent_at, COALESCE(ed.subject, '') AS subject,
                       SUBSTR(m.body_text, 1, 80) AS snippet
                FROM messages m
                JOIN messages_fts f ON f.rowid = m.id
                LEFT JOIN email_details ed ON ed.message_id = m.id
                WHERE messages_fts MATCH ?
                ORDER BY m.sent_at DESC
                LIMIT ?
                """,
                (query, limit),
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            click.echo("no matches.")
            return
        for r in rows:
            label = r["subject"] or r["snippet"]
            click.echo(f"[{r['source']}] {r['sent_at']}  {label}  (id={r['id']})")

    asyncio.run(_run())
```

Register in `src/accountpilot/cli.py`:
```python
from accountpilot.core.cli.search_cmd import search_cmd
# ...
cli.add_command(search_cmd)
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/cli/test_search_cmd.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/cli/search_cmd.py src/accountpilot/cli.py tests/accountpilot/unit/cli/test_search_cmd.py
git commit -m "$(cat <<'EOF'
feat(cli): add accountpilot search command

Run an FTS5 MATCH query against messages_fts, joined to messages and
email_details for display, ordered by sent_at desc, capped at --limit
(default 20). Prints '[source] sent_at  subject_or_snippet  (id=N)' or
'no matches.' when empty.
EOF
)"
```

---

### Task 17: CLI `status` command

**Files:**
- Create: `src/accountpilot/core/cli/status_cmd.py`
- Modify: `src/accountpilot/cli.py`
- Test: `tests/accountpilot/unit/cli/test_status_cmd.py`

Prints one row per account: source, identifier, owner name, message count, last_sync_at, last_error.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/cli/test_status_cmd.py`:
```python
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db


def _seed(db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
                "VALUES ('Aren', 'E', 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            await db.execute(
                "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
                "created_at, updated_at) VALUES (1, 'gmail', 'a@b.com', 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            await db.commit()
    asyncio.run(_run())


def test_status_lists_accounts(tmp_db_path: Path) -> None:
    _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0, result.output
    assert "gmail" in result.output
    assert "a@b.com" in result.output
    assert "Aren" in result.output


def test_status_empty_db(tmp_db_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["status", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0
    assert "no accounts" in result.output.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/cli/test_status_cmd.py -v`
Expected: failure on missing `status` command.

- [ ] **Step 3: Implement**

`src/accountpilot/core/cli/status_cmd.py`:
```python
"""accountpilot status"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from accountpilot.core.db.connection import open_db


@click.command("status")
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def status_cmd(db_path: Path) -> None:
    """Per-account health summary."""

    async def _run() -> None:
        async with open_db(db_path) as db:
            async with db.execute(
                """
                SELECT a.id, a.source, a.account_identifier, a.enabled,
                       p.name || COALESCE(' ' || p.surname, '') AS owner_name,
                       (SELECT COUNT(*) FROM messages m WHERE m.account_id=a.id) AS msg_count,
                       s.last_sync_at, s.last_error
                FROM accounts a
                JOIN people p ON p.id = a.owner_id
                LEFT JOIN sync_status s ON s.account_id = a.id
                ORDER BY a.id
                """
            ) as cur:
                rows = await cur.fetchall()
        if not rows:
            click.echo("no accounts.")
            return
        for r in rows:
            enabled = "on" if r["enabled"] else "off"
            click.echo(
                f"#{r['id']} [{enabled}] {r['source']:<10}  {r['account_identifier']:<30} "
                f"owner={r['owner_name']!r}  messages={r['msg_count']}  "
                f"last_sync={r['last_sync_at'] or '—'}  "
                f"last_error={r['last_error'] or '—'}"
            )

    asyncio.run(_run())
```

Register in `cli.py`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/cli/test_status_cmd.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/cli/status_cmd.py src/accountpilot/cli.py tests/accountpilot/unit/cli/test_status_cmd.py
git commit -m "feat(cli): add accountpilot status command for per-account health"
```

---

### Task 18: CLI `people` commands

**Files:**
- Create: `src/accountpilot/core/cli/people_cmds.py`
- Modify: `src/accountpilot/cli.py`
- Test: `tests/accountpilot/unit/cli/test_people_cmds.py`

`accountpilot people {list,show,merge,promote,demote}`. `merge` takes `--keep` and `--discard`.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/cli/test_people_cmds.py`:
```python
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db
from accountpilot.core.identity import find_or_create_person


def _seed_two_people(db_path: Path) -> tuple[int, int]:
    async def _run() -> tuple[int, int]:
        async with open_db(db_path) as db:
            a = await find_or_create_person(
                db, kind="email", value="a@x.com", default_name="A"
            )
            b = await find_or_create_person(
                db, kind="email", value="b@x.com", default_name="B"
            )
            return a, b
    return asyncio.run(_run())


def test_list_people(tmp_db_path: Path) -> None:
    _seed_two_people(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["people", "list", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0
    assert "a@x.com" in result.output
    assert "b@x.com" in result.output


def test_show_person(tmp_db_path: Path) -> None:
    a, _ = _seed_two_people(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(
        cli, ["people", "show", str(a), "--db-path", str(tmp_db_path)]
    )
    assert result.exit_code == 0
    assert "a@x.com" in result.output


def test_promote_demote_flips_owner_flag(tmp_db_path: Path) -> None:
    a, _ = _seed_two_people(tmp_db_path)
    runner = CliRunner()
    runner.invoke(cli, ["people", "promote", str(a), "--db-path", str(tmp_db_path)])
    out = runner.invoke(
        cli, ["people", "show", str(a), "--db-path", str(tmp_db_path)]
    ).output
    assert "owner: yes" in out
    runner.invoke(cli, ["people", "demote", str(a), "--db-path", str(tmp_db_path)])
    out = runner.invoke(
        cli, ["people", "show", str(a), "--db-path", str(tmp_db_path)]
    ).output
    assert "owner: no" in out


def test_merge_repoints_and_deletes(tmp_db_path: Path) -> None:
    a, b = _seed_two_people(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "people", "merge", "--keep", str(a), "--discard", str(b),
        "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0
    out = runner.invoke(cli, ["people", "list", "--db-path", str(tmp_db_path)]).output
    assert "b@x.com" in out  # identifier survives
    # Show discarded id should fail.
    show = runner.invoke(
        cli, ["people", "show", str(b), "--db-path", str(tmp_db_path)]
    )
    assert "not found" in show.output.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/cli/test_people_cmds.py -v`
Expected: failure on missing subcommand.

- [ ] **Step 3: Implement**

`src/accountpilot/core/cli/people_cmds.py`:
```python
"""accountpilot people ..."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import click

from accountpilot.core.db.connection import open_db
from accountpilot.core.identity import merge_people


@click.group("people")
def people_group() -> None:
    """Person/identifier management."""


def _db_option(f):
    return click.option(
        "--db-path",
        type=click.Path(path_type=Path),
        default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
    )(f)


@people_group.command("list")
@_db_option
@click.option("--owners/--all", default=False)
def people_list(db_path: Path, owners: bool) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            sql = (
                "SELECT p.id, p.name, p.surname, p.is_owner, "
                "GROUP_CONCAT(i.kind || ':' || i.value) AS idents "
                "FROM people p LEFT JOIN identifiers i ON i.person_id=p.id "
                + ("WHERE p.is_owner=1 " if owners else "")
                + "GROUP BY p.id ORDER BY p.id"
            )
            async with db.execute(sql) as cur:
                rows = await cur.fetchall()
        for r in rows:
            full = f"{r['name']} {r['surname'] or ''}".strip()
            owner = "*" if r["is_owner"] else " "
            click.echo(f"#{r['id']} {owner} {full:<30} {r['idents'] or ''}")
    asyncio.run(_run())


@people_group.command("show")
@click.argument("person_id", type=int)
@_db_option
def people_show(person_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            async with db.execute(
                "SELECT name, surname, is_owner FROM people WHERE id=?", (person_id,)
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                click.echo(f"person id={person_id} not found")
                return
            click.echo(f"id: {person_id}")
            click.echo(f"name: {row['name']} {row['surname'] or ''}".rstrip())
            click.echo(f"owner: {'yes' if row['is_owner'] else 'no'}")
            async with db.execute(
                "SELECT kind, value, is_primary FROM identifiers WHERE person_id=?",
                (person_id,),
            ) as cur:
                idents = await cur.fetchall()
            click.echo("identifiers:")
            for i in idents:
                star = " *" if i["is_primary"] else ""
                click.echo(f"  - {i['kind']}: {i['value']}{star}")
    asyncio.run(_run())


@people_group.command("promote")
@click.argument("person_id", type=int)
@_db_option
def people_promote(person_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "UPDATE people SET is_owner=1, updated_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), person_id),
            )
            await db.commit()
        click.echo(f"promoted #{person_id} to owner")
    asyncio.run(_run())


@people_group.command("demote")
@click.argument("person_id", type=int)
@_db_option
def people_demote(person_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "UPDATE people SET is_owner=0, updated_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), person_id),
            )
            await db.commit()
        click.echo(f"demoted #{person_id} from owner")
    asyncio.run(_run())


@people_group.command("merge")
@click.option("--keep", "keep_id", type=int, required=True)
@click.option("--discard", "discard_id", type=int, required=True)
@_db_option
def people_merge(keep_id: int, discard_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await merge_people(db, keep_id=keep_id, discard_id=discard_id)
        click.echo(f"merged #{discard_id} into #{keep_id}")
    asyncio.run(_run())
```

Register `people_group` in `cli.py`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/cli/test_people_cmds.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/cli/people_cmds.py src/accountpilot/cli.py tests/accountpilot/unit/cli/test_people_cmds.py
git commit -m "feat(cli): add accountpilot people {list,show,merge,promote,demote}"
```

---

### Task 19: CLI `accounts` commands

**Files:**
- Create: `src/accountpilot/core/cli/accounts_cmds.py`
- Modify: `src/accountpilot/cli.py`
- Test: `tests/accountpilot/unit/cli/test_accounts_cmds.py`

`accountpilot accounts {list,disable,delete}`. (`add` is deferred to SP3 in favor of editing `config.yaml` + running `setup`; the design's `add ...` interactive form is YAGNI for SP0.)

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/cli/test_accounts_cmds.py`:
```python
from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db


def _seed(db_path: Path) -> int:
    async def _run() -> int:
        async with open_db(db_path) as db:
            await db.execute(
                "INSERT INTO people (name, surname, is_owner, created_at, updated_at) "
                "VALUES ('Aren', NULL, 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            cur = await db.execute(
                "INSERT INTO accounts (owner_id, source, account_identifier, enabled, "
                "created_at, updated_at) VALUES (1, 'gmail', 'a@b.com', 1, ?, ?)",
                (datetime.now().isoformat(), datetime.now().isoformat()),
            )
            await db.commit()
            return cur.lastrowid
    return asyncio.run(_run())


def test_list_accounts(tmp_db_path: Path) -> None:
    _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, ["accounts", "list", "--db-path", str(tmp_db_path)])
    assert result.exit_code == 0
    assert "a@b.com" in result.output


def test_disable_account(tmp_db_path: Path) -> None:
    aid = _seed(tmp_db_path)
    runner = CliRunner()
    runner.invoke(cli, [
        "accounts", "disable", str(aid), "--db-path", str(tmp_db_path),
    ])
    out = runner.invoke(cli, [
        "accounts", "list", "--db-path", str(tmp_db_path),
    ]).output
    assert "[off]" in out


def test_delete_account_with_force(tmp_db_path: Path) -> None:
    aid = _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "accounts", "delete", str(aid), "--force",
        "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0
    out = runner.invoke(cli, [
        "accounts", "list", "--db-path", str(tmp_db_path),
    ]).output
    assert "a@b.com" not in out


def test_delete_without_force_aborts(tmp_db_path: Path) -> None:
    aid = _seed(tmp_db_path)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "accounts", "delete", str(aid),
        "--db-path", str(tmp_db_path),
    ], input="n\n")
    assert "aborted" in result.output.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/cli/test_accounts_cmds.py -v`
Expected: failure on missing subcommand.

- [ ] **Step 3: Implement**

`src/accountpilot/core/cli/accounts_cmds.py`:
```python
"""accountpilot accounts ..."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import click

from accountpilot.core.db.connection import open_db


@click.group("accounts")
def accounts_group() -> None:
    """Account management."""


def _db_option(f):
    return click.option(
        "--db-path",
        type=click.Path(path_type=Path),
        default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
    )(f)


@accounts_group.command("list")
@_db_option
def accounts_list(db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            async with db.execute(
                "SELECT a.id, a.source, a.account_identifier, a.enabled, "
                "p.name || COALESCE(' ' || p.surname, '') AS owner_name "
                "FROM accounts a JOIN people p ON p.id=a.owner_id "
                "ORDER BY a.id"
            ) as cur:
                rows = await cur.fetchall()
        for r in rows:
            state = "[on]" if r["enabled"] else "[off]"
            click.echo(
                f"#{r['id']} {state} {r['source']:<10}  {r['account_identifier']:<30} "
                f"owner={r['owner_name']!r}"
            )
    asyncio.run(_run())


@accounts_group.command("disable")
@click.argument("account_id", type=int)
@_db_option
def accounts_disable(account_id: int, db_path: Path) -> None:
    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "UPDATE accounts SET enabled=0, updated_at=? WHERE id=?",
                (datetime.now(UTC).isoformat(), account_id),
            )
            await db.commit()
        click.echo(f"disabled account #{account_id}")
    asyncio.run(_run())


@accounts_group.command("delete")
@click.argument("account_id", type=int)
@click.option("--force", is_flag=True)
@_db_option
def accounts_delete(account_id: int, force: bool, db_path: Path) -> None:
    if not force and not click.confirm(
        f"Delete account #{account_id} and all its messages?", default=False
    ):
        click.echo("aborted.")
        return

    async def _run() -> None:
        async with open_db(db_path) as db:
            await db.execute(
                "DELETE FROM messages WHERE account_id=?", (account_id,)
            )
            await db.execute(
                "DELETE FROM sync_status WHERE account_id=?", (account_id,)
            )
            await db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
            await db.commit()
        click.echo(f"deleted account #{account_id}")
    asyncio.run(_run())
```

Register in `cli.py`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/cli/test_accounts_cmds.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/cli/accounts_cmds.py src/accountpilot/cli.py tests/accountpilot/unit/cli/test_accounts_cmds.py
git commit -m "feat(cli): add accountpilot accounts {list,disable,delete}"
```

---

### Task 20: CLI `setup` command

**Files:**
- Create: `src/accountpilot/core/cli/setup_cmd.py`
- Modify: `src/accountpilot/cli.py`
- Test: `tests/accountpilot/unit/cli/test_setup_cmd.py`

Reads `~/.config/accountpilot/config.yaml` (or `--config`), populates `people`, `identifiers`, `accounts` idempotently. Owners are upserted; identifiers are added; accounts are upserted on `(source, identifier)`.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/unit/cli/test_setup_cmd.py`:
```python
from __future__ import annotations

import asyncio
from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli
from accountpilot.core.db.connection import open_db


def _write_config(path: Path) -> None:
    path.write_text("""
version: 1
owners:
  - name: Aren
    surname: Eren
    identifiers:
      - { kind: email, value: aren@x.com }
      - { kind: phone, value: "+905052490139" }
plugins:
  mail:
    enabled: true
    accounts:
      - identifier: aren@x.com
        owner: aren@x.com
        provider: gmail
        credentials_ref: "op://x/y/z"
""")


def test_setup_creates_owner_and_account(tmp_path: Path, tmp_db_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg)
    runner = CliRunner()
    result = runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0, result.output

    async def _check() -> None:
        async with open_db(tmp_db_path) as db:
            async with db.execute(
                "SELECT name FROM people WHERE is_owner=1"
            ) as cur:
                rows = [r["name"] for r in await cur.fetchall()]
            assert "Aren" in rows
            async with db.execute(
                "SELECT account_identifier FROM accounts"
            ) as cur:
                rows = [r["account_identifier"] for r in await cur.fetchall()]
            assert "aren@x.com" in rows
    asyncio.run(_check())


def test_setup_idempotent(tmp_path: Path, tmp_db_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    _write_config(cfg)
    runner = CliRunner()
    runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    result = runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code == 0

    async def _check() -> None:
        async with open_db(tmp_db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) AS c FROM accounts"
            ) as cur:
                assert (await cur.fetchone())["c"] == 1
            async with db.execute(
                "SELECT COUNT(*) AS c FROM people WHERE is_owner=1"
            ) as cur:
                assert (await cur.fetchone())["c"] == 1
    asyncio.run(_check())


def test_setup_missing_owner_reference_errors(tmp_path: Path, tmp_db_path: Path) -> None:
    cfg = tmp_path / "config.yaml"
    cfg.write_text("""
version: 1
owners:
  - name: Aren
    surname: null
    identifiers:
      - { kind: email, value: aren@x.com }
plugins:
  mail:
    enabled: true
    accounts:
      - identifier: a@b.com
        owner: nobody@nowhere.com
        provider: gmail
""")
    runner = CliRunner()
    result = runner.invoke(cli, [
        "setup", "--config", str(cfg), "--db-path", str(tmp_db_path),
    ])
    assert result.exit_code != 0
    assert "owner" in result.output.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/unit/cli/test_setup_cmd.py -v`
Expected: missing `setup` command.

- [ ] **Step 3: Implement**

`src/accountpilot/core/cli/setup_cmd.py`:
```python
"""accountpilot setup"""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from accountpilot.core.cas import CASStore
from accountpilot.core.config import IdentifierEntry, OwnerEntry, load_config
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage


@click.command("setup")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=Path.home() / ".config" / "accountpilot" / "config.yaml",
)
@click.option(
    "--db-path",
    type=click.Path(path_type=Path),
    default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
)
def setup_cmd(config_path: Path, db_path: Path) -> None:
    """Apply config.yaml to the DB (idempotent)."""

    cfg = load_config(config_path)
    cas_root = db_path.parent / "attachments"

    async def _run() -> None:
        async with open_db(db_path) as db:
            storage = Storage(db, CASStore(cas_root))
            owner_id_by_identifier: dict[str, int] = {}
            for owner in cfg.owners:
                pid = await storage.upsert_owner(
                    name=owner.name,
                    surname=owner.surname,
                    identifiers=[
                        Identifier(kind=i.kind, value=i.value)
                        for i in owner.identifiers
                    ],
                )
                for i in owner.identifiers:
                    owner_id_by_identifier[i.value.lower()] = pid

            for plugin_name, pcfg in cfg.plugins.items():
                if not pcfg.enabled:
                    continue
                for account in pcfg.accounts:
                    owner_pid = owner_id_by_identifier.get(account.owner.lower())
                    if owner_pid is None:
                        raise click.UsageError(
                            f"plugin '{plugin_name}' account "
                            f"{account.identifier!r} references unknown owner "
                            f"{account.owner!r} (not declared in owners[])"
                        )
                    source = account.provider or plugin_name
                    await storage.upsert_account(
                        source=source,
                        identifier=account.identifier,
                        owner_id=owner_pid,
                        credentials_ref=account.credentials_ref,
                    )
        click.echo(f"setup applied: {config_path} -> {db_path}")

    asyncio.run(_run())
```

Register in `cli.py`.

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/unit/cli/test_setup_cmd.py -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/cli/setup_cmd.py src/accountpilot/cli.py tests/accountpilot/unit/cli/test_setup_cmd.py
git commit -m "$(cat <<'EOF'
feat(cli): add accountpilot setup

Read config.yaml, upsert owners + their identifiers, upsert accounts on
(source, identifier). Idempotent: re-running with the same config is a
no-op. Each account's `owner` field must reference one of the declared
owner identifiers; an unknown reference raises a UsageError with the
unknown value in the message.
EOF
)"
```

---

### Task 21: Synthetic plugin fixture + integration test

**Files:**
- Create: `tests/accountpilot/fixtures/synthetic_plugin/__init__.py`
- Create: `tests/accountpilot/fixtures/synthetic_plugin/plugin.py`
- Create: `tests/accountpilot/integration/test_synthetic_plugin.py`

The synthetic plugin emits one fake email + one fake iMessage in `sync_once`. The integration test wires it up programmatically (not via entry point — tests are isolated from the installed env), runs sync, and verifies end-to-end behavior.

- [ ] **Step 1: Write the failing test**

All test `__init__.py` files were created in Task 1 — no extra package files needed here.

`tests/accountpilot/integration/test_synthetic_plugin.py`:
```python
from __future__ import annotations

from pathlib import Path

import aiosqlite

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage
from tests.accountpilot.fixtures.synthetic_plugin.plugin import SyntheticPlugin


async def test_synthetic_plugin_end_to_end(tmp_db_path: Path, tmp_runtime: Path) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        owner = await storage.upsert_owner(
            name="Aren", surname="E",
            identifiers=[
                Identifier(kind="email", value="aren@x.com"),
                Identifier(kind="phone", value="+15551234567"),
            ],
        )
        mail_account = await storage.upsert_account(
            source="gmail", identifier="aren@x.com", owner_id=owner,
        )
        im_account = await storage.upsert_account(
            source="imessage", identifier="+15551234567", owner_id=owner,
        )
        plugin = SyntheticPlugin(
            config={}, storage=storage, secrets=Secrets({}),
            mail_account_id=mail_account, imessage_account_id=im_account,
        )
        await plugin.sync_once(mail_account)
        await plugin.sync_once(im_account)

        # Both message types present.
        async with db.execute(
            "SELECT source, COUNT(*) AS c FROM messages GROUP BY source"
        ) as cur:
            counts = {r["source"]: r["c"] for r in await cur.fetchall()}
        assert counts == {"gmail": 1, "imessage": 1}

        # Attachment is on disk + indexed.
        async with db.execute("SELECT cas_path FROM attachments") as cur:
            rows = await cur.fetchall()
        assert len(rows) == 1
        assert (tmp_runtime / "attachments" / rows[0]["cas_path"]).exists()

        # FTS finds the synthetic body text.
        async with db.execute(
            "SELECT rowid FROM messages_fts WHERE messages_fts MATCH 'synthetic'"
        ) as cur:
            assert (await cur.fetchone()) is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `pytest tests/accountpilot/integration/test_synthetic_plugin.py -v`
Expected: ImportError on `tests.accountpilot.fixtures.synthetic_plugin.plugin`.

- [ ] **Step 3: Implement synthetic plugin**

`tests/accountpilot/fixtures/synthetic_plugin/plugin.py`:
```python
"""Synthetic test plugin: emits one canned email and one canned iMessage."""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from accountpilot.core.models import (
    AttachmentBlob,
    EmailMessage,
    IMessageMessage,
)
from accountpilot.core.plugin import AccountPilotPlugin


class SyntheticPlugin(AccountPilotPlugin):
    name: ClassVar[str] = "synthetic"

    def __init__(
        self,
        *,
        config,
        storage,
        secrets,
        mail_account_id: int,
        imessage_account_id: int,
    ) -> None:
        super().__init__(config=config, storage=storage, secrets=secrets)
        self._mail_account_id = mail_account_id
        self._imessage_account_id = imessage_account_id

    async def setup(self) -> None:
        return None

    async def backfill(self, account_id: int, *, since: datetime | None = None) -> None:
        await self.sync_once(account_id)

    async def sync_once(self, account_id: int) -> None:
        if account_id == self._mail_account_id:
            await self.storage.save_email(EmailMessage(
                account_id=account_id,
                external_id="<synthetic-1@example.com>",
                sent_at=datetime(2026, 5, 1, 12, 0),
                received_at=datetime(2026, 5, 1, 12, 0, 5),
                direction="inbound",
                from_address="Synthetic Sender <synth@example.com>",
                to_addresses=["aren@x.com"],
                cc_addresses=[],
                bcc_addresses=[],
                subject="Synthetic Subject",
                body_text="this is a synthetic message body",
                body_html=None,
                in_reply_to=None,
                references=[],
                imap_uid=1,
                mailbox="INBOX",
                gmail_thread_id=None,
                labels=["INBOX"],
                raw_headers={"Subject": "Synthetic Subject"},
                attachments=[
                    AttachmentBlob(
                        filename="attached.txt",
                        content=b"synthetic attachment bytes",
                        mime_type="text/plain",
                    )
                ],
            ))
        elif account_id == self._imessage_account_id:
            await self.storage.save_imessage(IMessageMessage(
                account_id=account_id,
                external_id="GUID-SYNTH-1",
                sent_at=datetime(2026, 5, 1, 13, 0),
                direction="inbound",
                sender_handle="+15559876543",
                chat_guid="chat-synth",
                participants=["+15551234567", "+15559876543"],
                body_text="synthetic imessage body",
                service="iMessage",
                is_read=True,
                date_read=None,
                attachments=[],
            ))

    async def daemon(self, account_id: int) -> None:
        return None

    async def teardown(self) -> None:
        return None
```

- [ ] **Step 4: Run to verify pass**

Run: `pytest tests/accountpilot/integration/test_synthetic_plugin.py -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add tests/accountpilot/integration tests/accountpilot/fixtures
git commit -m "$(cat <<'EOF'
test(integration): synthetic plugin end-to-end

Add a SyntheticPlugin fixture that emits one canned email (with
attachment) and one canned iMessage. The integration test seeds an owner
+ two accounts, runs sync_once for each, and verifies that messages,
email_details, imessage_details, attachments, CAS bytes, and FTS rows
all appear correctly.

This validates the AP-SP0 contract end-to-end before any real plugin
exists.
EOF
)"
```

---

### Task 22: Acceptance verification, README scaffold, lint/type clean

**Files:**
- Modify: `README.md` (short note + link to design doc)
- Create: `config.example.accountpilot.yaml` (sample config matching the design)

- [ ] **Step 1: Write `config.example.accountpilot.yaml`**

```yaml
# Example AccountPilot config — copy to ~/.config/accountpilot/config.yaml
# and edit. Apply with `accountpilot setup`.

version: 1

owners:
  - name: Aren
    surname: Eren
    identifiers:
      - { kind: email, value: aren@example.com }
      - { kind: phone, value: "+905052490139" }

plugins: {}   # SP1 adds the mail plugin; SP2 adds imessage
```

- [ ] **Step 2: Modify README.md**

Append (or replace its content with) a short note:

```markdown
# AccountPilot

A unified per-machine account sync framework. Pulls email, calendar,
iMessage, Telegram, and WhatsApp data into a local SQLite database
through a plugin architecture.

> **Status:** AP-SP0 in progress. The design supersedes the file+sidecar
> + outbound model previously described in `infra/specs/ACCOUNT_PILOT_SPEC.md`.

- Design: `docs/specs/2026-05-01-storage-rewrite-design.md`
- Roadmap & sub-slice plans: `docs/plans/`

The legacy `mailpilot` package continues to ship in this repo until SP1
deletes it.
```

- [ ] **Step 3: Run full test suite + lint + types**

```bash
pytest tests/accountpilot -q
ruff check src/accountpilot tests/accountpilot
mypy src/accountpilot
```

Expected:
- `pytest`: all green; coverage of every module touched in tasks 1–21.
- `ruff`: no violations.
- `mypy`: clean (strict mode is already configured).

If `mypy` flags issues, fix them inline (typically: missing `from __future__ import annotations`, untyped class attribute on `name: ClassVar[str]`, or `Any` slipping through Storage/plugin signatures — tighten and re-run).

- [ ] **Step 4: Run AP-SP0 acceptance scenarios manually**

These mirror the design doc's §7.1 acceptance list. Each scenario must succeed:

1. **Setup applies + is idempotent**

   ```bash
   mkdir -p ~/.config/accountpilot ~/runtime/accountpilot
   cp config.example.accountpilot.yaml ~/.config/accountpilot/config.yaml
   accountpilot setup
   accountpilot setup    # re-run; should be a no-op
   accountpilot status   # one account row visible
   ```

2. **Synthetic plugin populates all tables + CAS + FTS** — covered by the integration test in Task 21. Re-run for the record:

   ```bash
   pytest tests/accountpilot/integration -v
   ```

3. **`accountpilot people merge` re-points and deletes** — covered by Task 18 tests. Manual sanity check:

   ```bash
   accountpilot people list
   accountpilot people merge --keep 1 --discard 2   # if you have two test rows
   accountpilot people show 2   # should print "not found"
   ```

4. **Lint + types clean** — confirmed in Step 3.

If any acceptance scenario fails, open a follow-up task in this plan rather than papering over the issue.

- [ ] **Step 5: Commit + close out**

```bash
git add README.md config.example.accountpilot.yaml
git commit -m "$(cat <<'EOF'
docs: README + config.example for AP-SP0

Point readers at the storage-rewrite design doc and ship a config.example
matching the new owners-and-identifiers shape. Note that mailpilot ships
unchanged until SP1 removes it.
EOF
)"
```

After this commit, AP-SP0 is complete. The next plan is `2026-05-XX-accountpilot-ap-sp1.md`, covering the real mail plugin and the deletion of `src/mailpilot/`.

---

## Summary of commits (one per task)

| # | Subject |
|---|---------|
| 1 | feat(core): bootstrap accountpilot package skeleton |
| 2 | feat(core/db): add SQLite migration runner |
| 3 | feat(core/db): add 001_init.sql with full 9-table schema |
| 4 | feat(core/db): add async open_db helper |
| 5 | feat(core): add Pydantic domain models |
| 6 | feat(core): add content-addressed attachment store |
| 7 | feat(core/identity): add identifier normalization helpers |
| 8 | feat(core/identity): add find_or_create_person |
| 9 | feat(core/identity): add merge_people |
| 10 | feat(core/storage): add Storage.save_email |
| 11 | feat(core/storage): add Storage.save_imessage |
| 12 | feat(core/storage): add upsert_owner/account + latest_* helpers |
| 13 | feat(core): add AccountPilotPlugin base class + Secrets stub |
| 14 | feat(core): add YAML config loader with Pydantic validation |
| 15 | feat(cli): add accountpilot db {migrate,vacuum} |
| 16 | feat(cli): add accountpilot search command |
| 17 | feat(cli): add accountpilot status command for per-account health |
| 18 | feat(cli): add accountpilot people {list,show,merge,promote,demote} |
| 19 | feat(cli): add accountpilot accounts {list,disable,delete} |
| 20 | feat(cli): add accountpilot setup |
| 21 | test(integration): synthetic plugin end-to-end |
| 22 | docs: README + config.example for AP-SP0 |
