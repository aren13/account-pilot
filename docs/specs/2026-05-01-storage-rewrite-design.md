# AccountPilot Storage Rewrite — Design

> **Status:** Design / pre-implementation
> **Date:** 2026-05-01
> **Supersedes:** the file+sidecar+outbound storage model described in `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md` and `ARCHITECTURE.md` §6.13, §8.
> **Scope:** AccountPilot only. The downstream KB pipeline becomes a separate application and is out of scope here.

## 1. Motivation

The original AccountPilot design wrote one file + one sidecar JSON per item to a per-space directory tree, optionally routed through `~/outbound/<space>/` for Tailscale-shipping to a different machine where a KB pipeline would pick it up. This was load-bearing on three assumptions:

1. Per-space isolation across multiple machines in a Tailscale fleet.
2. The KB pipeline being co-designed with AccountPilot and watching directories.
3. Files-as-source-of-truth for both AccountPilot and downstream consumers.

All three are being dropped:

1. **No more spaces.** Single-machine deployment.
2. **KB pipeline becomes a separate application** with its own design.
3. **Local SQLite database becomes the source of truth.** Attachments stay on disk as content-addressed files.

The result is a much smaller, simpler AccountPilot whose only job is: connect to external services, normalize their data, persist into a local DB.

## 2. Non-goals

- Multi-machine sync. Single machine, one DB.
- Cross-process pubsub. Plugins are in-process; the KB app reads the DB.
- Backwards compatibility with `mail.db` from MailPilot. Existing data is dropped; a fresh sync rebuilds history from the source.
- Sidecar files, `sidecar-schemas` package, outbound directories, owner-aware adapter, space routing rules.
- Read/write parity. AccountPilot is read-only in v1 (sync from sources to DB). Send/reply flows are deferred.

## 3. Architecture overview

A single Python application (`accountpilot`) running on one macOS machine. Source-specific **plugins** sync data from external services and persist it through a typed **Storage** façade into a local SQLite database. Attachments are stored as content-addressed files on disk.

```
External source                Plugin                         Core (Storage)               Disk
─────────────────              ─────────────                  ──────────────               ─────
Gmail IMAP IDLE  ──fetch──▶   mail.daemon()
                              parse RFC822
                              build EmailMessage  ──save_email(msg)──▶  resolve people
                                                                        find_or_create
                                                                        dedup (msg_id)
                                                                        BEGIN TX
                                                                          insert messages
                                                                          insert email_details
                                                                          insert message_people
                                                                          insert attachments ─▶ CAS write
                                                                          insert FTS row
                                                                        COMMIT TX
chat.db change   ──watch──▶   imessage.daemon()
                              read new rows
                              build IMessageMessage ──save_imessage(msg)──▶ (same path, different extension table)
```

### 3.1 Components

- **Core** (`accountpilot.core`) — config, CLI, plugin loader, the `Storage` façade, identity resolution, SQLite schema + migrations, FTS5 index, CAS attachment writer. Knows nothing source-specific.
- **Plugins** (`accountpilot.plugins.*`) — each is a Python package implementing `AccountPilotPlugin` with 5 lifecycle hooks. v1 ships `mail` and `imessage`. Plugins import `Storage` and the Pydantic domain models from core.
- **CLI** (`accountpilot` entry point) — root Click group dispatching to plugin subcommands and core admin commands.
- **Daemon** — long-running process, one per plugin, managed by launchd. Each runs that plugin's `daemon()` hook (IMAP IDLE for mail; file-watch on `chat.db` for iMessage).

### 3.2 Architecture invariants (preserved)

- **Plugins never write to the DB or to disk directly.** They only call `Storage`. The façade is the sole writer.
- **Plugins never pick filenames or allocate IDs.** CAS paths and DB IDs are owned by core.
- **Plugins do not import each other.** Cross-plugin coordination, if ever needed, goes through core.
- **Secrets never enter the repo.** Resolved at runtime via `password_cmd` + 1Password CLI; cached in `~/runtime/accountpilot/secrets/` with mode 0600.
- **No arbitrary SQL exposed to plugins.** Plugins use typed `Storage` methods. Adding a query the plugin needs means adding an explicit `Storage` method.

### 3.3 Architecture invariants (deleted)

- Space isolation, owner-aware write paths, outbound directories, sidecar files, sidecar-schemas package, Tailscale shipping, the `~/spaces/<space>/meta.json` ownership protocol, file naming convention `{YYYYMMDD}_{hash6}.{ext}`.

## 4. Database schema

SQLite database at `~/runtime/accountpilot/accountpilot.db`. WAL mode for concurrent readers. Nine tables in three layers.

### 4.1 Identity layer

```sql
CREATE TABLE people (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL,
    surname      TEXT,
    is_owner     INTEGER NOT NULL DEFAULT 0,    -- 1 = Aren, Melis, etc.
    notes        TEXT,
    created_at   TIMESTAMP NOT NULL,
    updated_at   TIMESTAMP NOT NULL
);

CREATE TABLE identifiers (
    id           INTEGER PRIMARY KEY,
    person_id    INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,                  -- 'email' | 'phone' | 'imessage_handle' | 'telegram_username' | …
    value        TEXT NOT NULL,                  -- normalized: lowercase email; E.164 phone; etc.
    is_primary   INTEGER NOT NULL DEFAULT 0,
    created_at   TIMESTAMP NOT NULL,
    UNIQUE (kind, value)
);
CREATE INDEX idx_identifiers_person ON identifiers(person_id);

CREATE TABLE accounts (
    id                  INTEGER PRIMARY KEY,
    owner_id            INTEGER NOT NULL REFERENCES people(id),    -- must have is_owner=1 (app-level check)
    source              TEXT NOT NULL,                              -- 'gmail' | 'imessage' | …
    account_identifier  TEXT NOT NULL,                              -- email address, phone, etc.
    display_name        TEXT,
    credentials_ref     TEXT,                                       -- e.g. 'op://Personal/gmail-personal/password'
    enabled             INTEGER NOT NULL DEFAULT 1,
    backfilled_at       TIMESTAMP,
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL,
    UNIQUE (source, account_identifier)
);
```

### 4.2 Message layer

```sql
CREATE TABLE messages (
    id            INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL REFERENCES accounts(id),
    source        TEXT NOT NULL,                          -- denormalized from accounts.source
    external_id   TEXT NOT NULL,                          -- IMAP Message-ID, iMessage GUID, …
    thread_id     TEXT,
    sent_at       TIMESTAMP NOT NULL,
    received_at   TIMESTAMP,
    body_text     TEXT NOT NULL DEFAULT '',
    body_html     TEXT,
    direction     TEXT NOT NULL,                          -- 'inbound' | 'outbound'
    created_at    TIMESTAMP NOT NULL,
    UNIQUE (account_id, external_id)
);
CREATE INDEX idx_messages_thread     ON messages(thread_id);
CREATE INDEX idx_messages_sent_at    ON messages(sent_at);
CREATE INDEX idx_messages_account    ON messages(account_id);

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
    service      TEXT NOT NULL,           -- 'iMessage' | 'SMS'
    is_from_me   INTEGER NOT NULL,
    is_read      INTEGER NOT NULL DEFAULT 0,
    date_read    TIMESTAMP
);

CREATE TABLE message_people (
    message_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    person_id    INTEGER NOT NULL REFERENCES people(id),
    role         TEXT NOT NULL,           -- 'from' | 'to' | 'cc' | 'bcc' | 'participant'
    PRIMARY KEY (message_id, person_id, role)
);
CREATE INDEX idx_message_people_person ON message_people(person_id);

CREATE TABLE attachments (
    id            INTEGER PRIMARY KEY,
    message_id    INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    content_hash  TEXT NOT NULL,           -- sha256 hex
    mime_type     TEXT,
    size_bytes    INTEGER NOT NULL,
    cas_path      TEXT NOT NULL            -- 'ab/cd/abcd…ef.bin'
);
CREATE INDEX idx_attachments_message ON attachments(message_id);
CREATE INDEX idx_attachments_hash    ON attachments(content_hash);
```

### 4.3 Search layer

```sql
CREATE VIRTUAL TABLE messages_fts USING fts5(
    body_text,
    subject,                                -- NULL for non-email rows
    content=''                              -- contentless: source data lives in messages/email_details
);

-- Triggers (omitted here, defined in 001_init.sql) keep messages_fts in sync with
-- messages and email_details on INSERT / UPDATE / DELETE.
```

### 4.4 Migrations

Plain SQL files numbered `001_init.sql`, `002_*.sql`, applied in order. Version stored in a `schema_version` table. No Alembic — overkill for an embedded DB owned by one app.

### 4.5 CAS layout

```
~/runtime/accountpilot/attachments/
  ab/cd/abcd1234…ef.bin     <- sha256 = abcd1234…ef
  ef/01/ef01abcd…12.bin
```

Two-level fanout (`hash[:2]/hash[2:4]/hash`) prevents 100k+ files in one directory. Writes are atomic (temp file + rename). Idempotent: if the CAS path already exists, skip the write — content-addressing guarantees identical bytes.

### 4.6 Concrete examples

| Real-world entity | Rows |
|---|---|
| `ardaeren13@gmail.com` (Aren's Gmail) | `people(name='Arda', surname='Eren', is_owner=1)` + `identifiers(kind='email', value='ardaeren13@gmail.com')` + `accounts(source='gmail', account_identifier='ardaeren13@gmail.com', owner_id=…)` |
| Aren's WhatsApp `+905052490139` | Same `people.id`, additional `identifiers(kind='phone', value='+905052490139')` + `accounts(source='whatsapp', …)` |
| `melis@contentmontent.com` | Separate `people(name='Melis', surname='B', is_owner=1)` + her own identifiers + her own gmail account |

## 5. Plugin contract

### 5.1 `AccountPilotPlugin` base class

Five lifecycle hooks, preserved from the original design. Each hook takes an `account_id` (an integer FK into `accounts`) rather than a space name.

```python
class AccountPilotPlugin(ABC):
    name: ClassVar[str]                                    # "mail", "imessage"

    def __init__(self, config: PluginConfig, storage: Storage, secrets: Secrets):
        self.config = config
        self.storage = storage
        self.secrets = secrets

    @abstractmethod
    async def setup(self) -> None: ...
    # First-run: create runtime dirs, prompt for missing config, register accounts in DB
    # if not already there. Idempotent.

    @abstractmethod
    async def backfill(self, account_id: int, *, since: datetime | None = None) -> None: ...
    # One-shot historical pull. Calls storage.save_*() per item. On success, writes
    # accounts.backfilled_at.

    @abstractmethod
    async def sync_once(self, account_id: int) -> None: ...
    # Single bounded incremental pass. Returns when caught up.

    @abstractmethod
    async def daemon(self, account_id: int) -> None: ...
    # Long-running. Survives transient errors and reconnects. launchd manages process.

    @abstractmethod
    async def teardown(self) -> None: ...
    # Clean shutdown of sockets, file handles, watchers. Called on SIGTERM.

    def cli(self) -> click.Group | None:
        return None
```

A single plugin instance handles all enabled accounts of its source. The `daemon()` method either iterates accounts sequentially or spawns one asyncio task per account with a per-task supervisor (one account dying must not kill the others).

### 5.2 `Storage` façade

The single write API. Plugins only see this interface; nothing else writes to the DB or CAS.

```python
class Storage:
    """Sole writer to the SQLite DB and CAS attachment store."""

    # ─── Message ingest (the hot path) ─────────────────────────────────────
    async def save_email(self, msg: EmailMessage) -> SaveResult: ...
    async def save_imessage(self, msg: IMessageMessage) -> SaveResult: ...
    # Each method:
    #   1. Opens a transaction.
    #   2. Resolves identifiers → person_ids via find_or_create.
    #   3. Checks dedup by (account_id, external_id). If present → SaveResult(action='skipped').
    #   4. Inserts into messages, <source>_details, message_people, attachments.
    #   5. Writes attachment bytes to CAS (idempotent: skip if hash exists).
    #   6. Commits. FTS row appears via trigger.

    # ─── Account & owner management (CLI / setup, not hot path) ────────────
    async def upsert_account(self, source: str, identifier: str, owner_id: int,
                             credentials_ref: str | None = None) -> int: ...
    async def upsert_owner(self, name: str, surname: str | None,
                           identifiers: list[Identifier]) -> int: ...

    # ─── Read helpers (resumable sync) ─────────────────────────────────────
    async def latest_external_id(self, account_id: int) -> str | None: ...
    async def latest_sent_at(self, account_id: int) -> datetime | None: ...

    # ─── Batched ops (backfill speedup) ────────────────────────────────────
    @asynccontextmanager
    async def batch(self) -> AsyncIterator[BatchStorage]: ...
```

`SaveResult` is `{'action': 'inserted' | 'skipped' | 'updated', 'message_id': int}`. `inserted` = new row written. `skipped` = `(account_id, external_id)` already present and contents unchanged. `updated` = row existed but mutable fields changed (e.g., Gmail labels on an existing message); reserved for future use, v1 implementations may always return `inserted` or `skipped`.

### 5.3 Domain models

Pydantic v2 models in `accountpilot.core.models`, shared between plugins and storage:

```python
class EmailMessage(BaseModel):
    account_id: int
    external_id: str                          # Message-ID
    sent_at: datetime
    received_at: datetime | None
    direction: Literal['inbound', 'outbound']
    from_address: str                         # raw — Storage resolves to person_id
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

class IMessageMessage(BaseModel):
    account_id: int
    external_id: str                          # iMessage GUID
    sent_at: datetime
    direction: Literal['inbound', 'outbound']
    sender_handle: str                        # raw — Storage resolves
    chat_guid: str
    participants: list[str]                   # raw handles
    body_text: str
    service: Literal['iMessage', 'SMS']
    is_read: bool
    date_read: datetime | None
    attachments: list[AttachmentBlob]
```

### 5.4 Identity resolution

Inside `Storage._find_or_create_person(kind, value)`:

1. **Normalize** `value`: lowercase emails, strip `mailto:`; phones to E.164; iMessage handles to either E.164 or lowercase email.
2. **Lookup** `identifiers WHERE kind=? AND value=?`. If hit → return `person_id`.
3. **Miss** → create a `people` row with `is_owner=0`, name parsed from address ("Melis B" `<melis@…>` → `name='Melis', surname='B'`) or `null` if unparseable; create the `identifiers` row; return new `person_id`.
4. **Owner promotion is manual.** `accountpilot people promote <id>` flips `is_owner = 1`. No auto-promotion.
5. **Manual merge** for cross-identifier duplicates: `accountpilot people merge <keep_id> <discard_id>` re-points all FKs from the discarded person to the kept one and deletes the discarded row.

## 6. Filesystem & runtime layout

### 6.1 Config (XDG-compliant)

```
~/.config/accountpilot/
  config.yaml
```

### 6.2 Operational state (gitignored, never synced)

```
~/runtime/accountpilot/
  accountpilot.db                 SQLite database
  accountpilot.db-wal             WAL files
  accountpilot.db-shm
  attachments/                    CAS root
    ab/cd/abcd1234…ef.bin
    ef/01/ef01abcd…12.bin
  logs/
    mail.log
    imessage.log
    core.log
  tmp/                            in-flight downloads, atomic-rename targets
  secrets/                        resolved credentials cache (dir 0700, files 0600)
```

### 6.3 Source code (post-rename)

```
src/accountpilot/
  __init__.py
  __main__.py
  cli.py
  core/
    config.py
    storage.py
    models.py
    identity.py
    cas.py
    db/
      __init__.py
      schema.py                   connection setup, FTS5 triggers
      migrations/
        001_init.sql
    auth.py
    plugin.py
  plugins/
    mail/
      __init__.py
      plugin.py                   MailPlugin(AccountPilotPlugin)
      imap/                       (ported from src/mailpilot/imap/)
      parser.py                   RFC822 → EmailMessage
      cli.py
    imessage/
      __init__.py
      plugin.py                   IMessagePlugin(AccountPilotPlugin)
      reader.py                   chat.db reader
      watcher.py                  file-watch on chat.db
      cli.py
tests/
  unit/
  integration/
```

### 6.4 Deletions vs. current repo

- `src/mailpilot/database.py` → replaced by `core/db/`.
- `src/mailpilot/search/` (Xapian) → replaced by FTS5.
- `src/mailpilot/tags/` → out of v1 scope.
- `src/mailpilot/events/` → no event bus.
- `mail.db` → dropped; fresh sync rebuilds.

### 6.5 `config.yaml` shape

```yaml
version: 1

owners:
  - name: Arda
    surname: Eren
    identifiers:
      - { kind: email, value: ardaeren13@gmail.com }
      - { kind: phone, value: "+905052490139" }
  - name: Melis
    surname: B
    identifiers:
      - { kind: email, value: melis@contentmontent.com }

plugins:
  mail:
    enabled: true
    accounts:
      - identifier: ardaeren13@gmail.com
        owner: ardaeren13@gmail.com           # references an identifier above
        provider: gmail                       # 'gmail' | 'outlook' | 'imap-generic'
        credentials_ref: "op://Personal/gmail-personal/password"
      - identifier: melis@contentmontent.com
        owner: melis@contentmontent.com
        provider: gmail
        credentials_ref: "op://Shared/melis-gmail/password"
    idle_timeout_seconds: 1740
  imessage:
    enabled: true
    accounts:
      - identifier: "+905052490139"
        owner: "+905052490139"
        chat_db_path: ~/Library/Messages/chat.db
```

`accountpilot setup` reads this, populates `people` + `identifiers` + `accounts`, and is idempotent. The `owner: <identifier-string>` field references one of the owner's identifiers (e.g., `ardaeren13@gmail.com`); `setup` resolves it by looking up the `identifiers` row and using its `person_id` as the new `accounts.owner_id`. Removing an account from YAML sets `accounts.enabled = 0` (soft-disable). Hard delete requires an explicit `accountpilot accounts delete` command.

### 6.6 CLI surface

```
accountpilot setup                          apply config.yaml to DB (idempotent)
accountpilot status                         per-account health summary

accountpilot mail backfill <account>
accountpilot mail sync <account>
accountpilot mail daemon                    long-running, all enabled mail accounts

accountpilot imessage backfill <account>
accountpilot imessage sync <account>
accountpilot imessage daemon

accountpilot people list [--owners] [--search <q>]
accountpilot people show <id>
accountpilot people merge <keep_id> <discard_id>
accountpilot people promote <id>            is_owner = 1
accountpilot people demote <id>

accountpilot accounts list
accountpilot accounts add ...
accountpilot accounts disable <id>
accountpilot accounts delete <id>           cascades; confirms

accountpilot search "<query>"               FTS5 query
accountpilot db migrate
accountpilot db vacuum
```

Two launchd jobs: `com.accountpilot.mail.daemon`, `com.accountpilot.imessage.daemon`. Failure domains kept separate.

### 6.7 Logging & observability

- Stdlib `logging`, JSON formatter, one file per plugin under `~/runtime/accountpilot/logs/`. launchd handles rotation.
- `accountpilot status` reads from a `sync_status` table (last sync, last error per account) updated by `Storage` after every `save_*`.
- No metrics endpoint, no Prometheus, no OTel, no Sentry in v1.

## 7. Roadmap

Four sequential, gating sub-slices. Each ends with a hardware acceptance test on AE.

### 7.1 AP-SP0 — Core foundation

> **Goal:** Build `accountpilot.core` with schema, `Storage` façade, Pydantic models, identity resolution, CAS attachment writer, plugin loader, CLI scaffolding, migrations. Prove the contract with a synthetic plugin.

**Tasks**
- Create `src/accountpilot/` package; `pyproject.toml` adds `accountpilot` alongside `mailpilot` (both ship until SP1).
- `migrations/001_init.sql` with all 9 tables + FTS5 triggers.
- Implement `core/models.py`, `core/storage.py`, `core/identity.py`, `core/cas.py`, `core/db/schema.py`.
- Implement `core/plugin.py` (base class + entry-point-based discovery).
- Implement `core/config.py` (YAML loader + Pydantic validation).
- Implement `core/cli.py` with `setup`, `status`, `people *`, `accounts *`, `db migrate`, `db vacuum`, `search`.
- Synthetic plugin in `tests/fixtures/synthetic_plugin/` exercising `save_email` and `save_imessage`.
- Unit tests: identity resolution, dedup, CAS hashing, FTS triggers, migrations. Integration test: synthetic plugin end-to-end.

**Acceptance**
1. `accountpilot setup` reads sample `config.yaml` with owners and zero plugins; `people` and `accounts` populate; re-running is a no-op.
2. Synthetic plugin run inserts rows in all expected tables; CAS file appears at expected path; `accountpilot search "synthetic"` returns the message.
3. `accountpilot people merge` correctly re-points all FKs and deletes the discarded person.
4. ruff + mypy clean; all tests pass.

### 7.2 AP-SP1 — Mail plugin (one Gmail account)

> **Goal:** Real IMAP, real Gmail account, full sync loop. After this, `mailpilot` is deleted from the repo.

**Tasks**
- Create `src/accountpilot/plugins/mail/`; port IMAP client from `src/mailpilot/imap/` with adapter changes to call `Storage.save_email` instead of writing to `mail.db`.
- `plugins/mail/parser.py` — RFC822 → `EmailMessage` (subject decoding, MIME walk, attachment extraction, header parsing).
- `MailPlugin` with all 5 hooks. `daemon()` wraps IMAP IDLE; `sync_once` does a single fetch pass; `backfill` walks UIDs since `accounts.backfilled_at`.
- Auth: `password_cmd` + 1Password CLI. OAuth deferred to SP3.
- `accountpilot mail …` CLI subcommands.
- launchd plist `com.accountpilot.mail.daemon` (deploy via `~/Projects/infra/configs/machines/ae/launchd/`).
- **Delete** `src/mailpilot/`. Update `pyproject.toml` to drop the `mailpilot` package. Update `README.md`, `CLAUDE.md`, `CHANGELOG.md`.
- Migrate the existing pytest suite for mail logic into `tests/unit/plugins/mail/`.

**Acceptance** (live hardware test on AE)
1. New email at `ardaeren13@gmail.com` → row in `messages` + `email_details` within ~5s of IDLE notification.
2. Attachment-bearing email → file in CAS; `attachments` row present; `content_hash` matches file.
3. Sender resolves to a `people` row (created if new, reused if seen before).
4. `accountpilot search "<phrase from email body>"` returns the email at top.
5. Daemon survives 24h continuous run; reconnects after deliberate network blip; no duplicate rows on reconnect.
6. `src/mailpilot/` no longer exists; `git grep mailpilot` returns only CHANGELOG and migration-note references.

### 7.3 AP-SP2 — iMessage plugin

> **Goal:** Add a second source. iMessage proves the plugin abstraction holds against a non-IMAP sync model.

**Tasks**
- `src/accountpilot/plugins/imessage/`.
- `reader.py`: open `~/Library/Messages/chat.db` read-only; join `message` + `chat` + `handle` + `attachment`; normalize to `IMessageMessage`.
- `watcher.py`: file-watch on `chat.db` (watchdog or kqueue); debounce; on change, query rows with `ROWID > last_seen`.
- `IMessagePlugin` with 5 hooks. `daemon()` runs the watcher; `backfill` reads everything since `accounts.backfilled_at`; `sync_once` does one debounced poll.
- Document Full Disk Access requirement for the launchd job's Python interpreter.
- launchd plist `com.accountpilot.imessage.daemon`.

**Acceptance** (live hardware test on AE)
1. Test iMessage from another device → row in `messages` + `imessage_details` within ~5s.
2. Sender handle resolves to a `people` row; cross-source identity works (a phone already in `identifiers` from a Gmail correspondent links to the same person).
3. Group chat → multiple `message_people` rows with `role='participant'`.
4. iMessage attachment → CAS file + `attachments` row.
5. Daemon survives `chat.db` rotation event without crashing; no duplicate rows.

### 7.4 AP-SP3 — Multi-account mail + OAuth + polish

> **Goal:** Production-shape v1. All Aren's + Melis's mail accounts, OAuth, search UX, owner/people management commands.

**Tasks**
- OAuth: Gmail (Google) + Outlook (Microsoft) flows in `core/auth.py`. Refresh-token storage in `~/runtime/accountpilot/secrets/` (mode 0600). Per-account `auth_method: oauth | password`.
- Add 2 more mail accounts.
- `accountpilot search` improvements: `--from`, `--owner`, `--source`, `--since`, `--limit`, snippet highlighting.
- `accountpilot people` polish: detect probable duplicates and propose merges.
- `accountpilot status` enriched: per-account last-sync, message count, error count, time since last successful IDLE keepalive.
- Documentation pass: rewrite `README.md`, `ARCHITECTURE.md`, `CLAUDE.md`, `ROADMAP.md`. Decide fate of `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md` (rewrite or mark superseded — needs an infra-side decision).

**Acceptance**
1. All 3+ mail accounts run concurrently under one `mail.daemon`; one account dying does not kill the others.
2. OAuth refresh works after a 24h idle window without manual intervention.
3. Search across all accounts + sources returns sensible top-N for representative queries.
4. Cross-source identity: an email from a contact and an iMessage from the same person's phone resolve to one `people` row.

### 7.5 Cross-cutting

- Each sub-slice ends with a hardware acceptance test on AE. No ratchet to next until acceptance passes.
- Plans live in `~/Projects/infra/specs/plans/`. Naming: `2026-05-XX-accountpilot-ap-spN.md`.
- Architecture deltas logged in `~/Projects/infra/specs/DELTAS.md` first; a rewritten `ACCOUNT_PILOT_SPEC.md` (or "superseded" marker) lands after SP1.
- pytest + ruff + mypy + pre-commit retained. No coverage % gate. Every new module needs at least happy-path tests.

## 8. Open questions / downstream consequences

These are flagged for separate buy-in, not decided here.

- **Infra spec freeze.** The infra repo's `ACCOUNT_PILOT_SPEC.md` and `ARCHITECTURE.md` §6.13 / §8 describe the old model. They need either rewrite or "superseded" markers. This is an infra-side conversation.
- **KB pipeline read API.** The KB pipeline becomes a separate app reading from `accountpilot.db`. Its design is out of scope here, but its read mechanism (poll a table? subscribe to SQLite WAL? consume an outbox?) is something AccountPilot will eventually accommodate. Worth keeping the *option* of a thin "outbox" table in mind during SP0 — but not building it.
- **CLAUDE.md and ROADMAP.md** in this repo describe the old model. Both need a rewrite pass once this design is approved (probably as part of SP0 task list).
