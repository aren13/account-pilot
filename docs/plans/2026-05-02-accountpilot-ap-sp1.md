# AccountPilot AP-SP1 — Real Mail Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the existing IMAP/RFC822 mail logic from `src/mailpilot/` into a new `accountpilot.plugins.mail` package, wire it into the SP0 plugin contract, and delete `src/mailpilot/`. After this, AccountPilot can sync one Gmail account end-to-end via IMAP IDLE, with all data flowing through the SP0 Storage façade.

**Architecture:** A new mail plugin (`accountpilot.plugins.mail.plugin:MailPlugin`) implements the 5-hook lifecycle. It composes a ported async IMAP client, a ported IDLE listener, a new typed RFC822 parser that produces `EmailMessage` Pydantic models, and a new sync orchestrator that calls `Storage.save_email`. Auth resolves via a real `password_cmd:` URI scheme that pipes through to 1Password CLI. Plugin discovery uses the `accountpilot.plugins` entry point group from SP0. After SP1, `src/mailpilot/` is removed and the legacy `mailpilot` console script disappears.

**Tech Stack:** Python 3.11+, `aioimaplib` (already a dep), Pydantic v2, Click, aiosqlite, `phonenumbers`, `msal` (XOAUTH2/OAuth — already a dep). pytest + pytest-asyncio (asyncio_mode=auto). Strict mypy + ruff. Existing project conventions retained.

**Reference spec:** `docs/specs/2026-05-01-storage-rewrite-design.md` §7.2 — read this if any task is ambiguous. The acceptance criteria in §7.2 are the gate this plan must clear.

---

## Pre-flight Notes

- **Working branch:** `main` (matches user's mainline workflow established in SP0).
- **Test isolation:** all DB-touching tests reuse SP0's `tmp_db` / `tmp_db_path` / `tmp_runtime` fixtures from `tests/accountpilot/conftest.py`. New plugin-specific fixtures live under `tests/accountpilot/plugins/mail/`.
- **TDD discipline:** every new module gets a failing test first, then implementation. **Port tasks** (Tasks 5–9) deviate slightly: the existing tests already pass; the work is verifying they still pass after the move + import changes.
- **Async:** `aioimaplib` and `aiosqlite` are both async. `MailPlugin` hooks are async; the CLI wraps them with `asyncio.run`.
- **No new schema migrations.** SP1 uses the schema SP0 built. No `002_*.sql` file gets created.
- **Acceptance:** Tasks 18 ends with the seven hardware scenarios from spec §7.2. The user runs these on AE; they're not automated.

---

## File Structure

**Created:**

```
src/accountpilot/plugins/mail/
  __init__.py
  plugin.py                       # MailPlugin(AccountPilotPlugin) — 5 hooks
  config.py                       # MailPluginConfig, MailAccountConfig (Pydantic)
  parser.py                       # RFC822 bytes → EmailMessage (typed)
  sync.py                         # orchestrate fetch → parse → Storage.save_email
  oauth.py                        # ported from src/mailpilot/oauth.py
  imap/
    __init__.py
    client.py                     # ported from src/mailpilot/imap/client.py
    idle.py                       # ported from src/mailpilot/imap/idle.py
  providers/
    __init__.py                   # ported from src/mailpilot/providers/__init__.py
    gmail.py                      # ported from src/mailpilot/providers/gmail.py
    outlook.py                    # ported from src/mailpilot/providers/outlook.py
  cli.py                          # mail backfill, sync, daemon Click subgroup

tests/accountpilot/plugins/
  __init__.py
  mail/
    __init__.py
    conftest.py                   # FakeImapClient fixture for sync/plugin tests
    test_parser.py                # RFC822 → EmailMessage cases
    test_config.py
    test_sync.py
    test_plugin.py                # MailPlugin lifecycle tests with FakeImap
    test_cli.py                   # mail backfill/sync subcommands
    test_imap_client.py           # ported from tests/test_imap_client.py
    test_idle.py                  # ported from tests/test_idle.py

~/Projects/infra/configs/machines/ae/launchd/
  com.accountpilot.mail.daemon.plist     # launchd job; deploys manually
```

**Modified:**

```
pyproject.toml                    # rename project to accountpilot, drop mailpilot
                                  # script + package; register MailPlugin entry point
src/accountpilot/core/auth.py     # real password_cmd resolver (was a stub in SP0)
src/accountpilot/core/storage.py  # add latest_imap_uid helper
src/accountpilot/core/identity.py # upsert_owner: auto-merge cross-person collisions

CLAUDE.md                         # SP0 → SP1 status update
README.md                         # AP-SP1 status; remove "MailPilot" section
CHANGELOG.md                      # SP1 entry
ROADMAP.md                        # mark AP-SP1 done; AP-SP2 next
```

**Deleted (in Task 16):**

```
src/mailpilot/                    # entire package
tests/test_api.py
tests/test_cli.py
tests/test_composer.py
tests/test_config.py
tests/test_daemon.py
tests/test_database.py
tests/test_events.py
tests/test_idle.py                # already migrated in Task 7
tests/test_imap_client.py         # already migrated in Task 6
tests/test_parser.py              # superseded by tests/accountpilot/plugins/mail/test_parser.py
tests/test_search.py
tests/test_smtp.py
tests/test_sync.py
tests/test_tags.py
tests/test_threading.py
tests/conftest.py                 # mailpilot-specific; check before deleting
```

`mail.db` (if present at `~/.mailpilot/mail.db` or repo root) is dropped — fresh `accountpilot setup` rebuilds.

---

### Task 1: Pre-flight — pyproject project rename and package switch

**Files:**
- Modify: `pyproject.toml`

This task flips the project's published name and clears the way for SP1's deletions in Task 16. The `mailpilot` package files still exist on disk after this task, but the `mailpilot` console script and the package's wheel inclusion are removed.

- [ ] **Step 1: Apply pyproject changes**

In `pyproject.toml`:

```toml
[project]
name = "accountpilot"                                  # WAS "mailpilot"
version = "0.1.0"
description = "Unified per-machine account sync framework — email, calendar, iMessage, Telegram, WhatsApp"
license = "Apache-2.0"
requires-python = ">=3.11"
authors = [{ name = "ae" }]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: Apache Software License",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Communications :: Email",
    "Typing :: Typed",
]
dependencies = [
    # unchanged
]

[project.optional-dependencies]
dev = [
    # unchanged
]

[project.scripts]
accountpilot = "accountpilot.cli:cli"                  # was: mailpilot AND accountpilot; now only accountpilot

[project.urls]
Homepage = "https://github.com/aren13/account-pilot"   # WAS ae/mail-pilot
Repository = "https://github.com/aren13/account-pilot"
Issues = "https://github.com/aren13/account-pilot/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/accountpilot"]                        # WAS ["src/mailpilot", "src/accountpilot"]

[project.entry-points."accountpilot.plugins"]
mail = "accountpilot.plugins.mail.plugin:MailPlugin"   # NEW — registered ahead of MailPlugin landing in Task 12

# (other [tool.*] sections unchanged)
```

After this change:
- `pip install -e .` no longer ships the `mailpilot` package or registers the `mailpilot` console command.
- The entry point points at `MailPlugin`, which doesn't exist yet — that's fine; nothing loads plugins until Task 14's CLI integration.
- All AccountPilot tests still pass because `mailpilot` was already a separate, independent package.

- [ ] **Step 2: Reinstall to reflect the script changes**

```bash
pip install -e ".[dev]"
which mailpilot      # should be unset / not on PATH after install
which accountpilot   # should still resolve
accountpilot --help  # should print Click help with db, search, status, people, accounts, setup subcommands
```

- [ ] **Step 3: Verify all SP0 tests still pass**

```bash
pytest tests/accountpilot -q
```

Expected: 84+ passed. (`mailpilot` tests in `tests/test_*.py` may now fail or skip because the package is no longer installed in develop mode under that name — those are deleted in Task 16.)

If any `tests/test_*.py` mailpilot tests now fail, that's expected and not a blocker for this commit. They'll all be deleted in Task 16. Use `--ignore=tests/test_api.py --ignore=tests/test_cli.py …` if needed to keep the SP0 suite green during this task.

Cleaner: `pytest tests/accountpilot -q` only runs the SP0+ suite. Use that as the verification command.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "$(cat <<'EOF'
chore: rename project to accountpilot; drop mailpilot script + package

Flip pyproject.toml's project name from `mailpilot` to `accountpilot`,
remove the `mailpilot` console script, and stop including
`src/mailpilot/` in the wheel build. Register the (not-yet-existent)
`accountpilot.plugins.mail.plugin:MailPlugin` entry point so plugin
discovery resolves it once Task 12 lands the class.

The mailpilot source tree stays on disk through Tasks 2-15 so its IMAP /
IDLE / OAuth / parser code remains importable for the porting tasks.
Task 16 deletes it.
EOF
)"
```

---

### Task 2: Real `Secrets` resolver with `password_cmd` scheme

**Files:**
- Modify: `src/accountpilot/core/auth.py`
- Modify: `tests/accountpilot/unit/core/test_plugin_base.py` (extend Secrets coverage)
- Test: `tests/accountpilot/unit/core/test_auth.py` (new)

SP0 shipped `Secrets` as a `frozen dataclass` wrapping a `dict[str, str]`. SP1 needs a real resolver that recognizes `password_cmd:<shell command>` URIs and runs them. Other schemes (`op://...`) deferred to SP3 — for SP1 we just need command-based resolution that works with `1password-cli`'s `op read` invoked from a shell wrapper.

The new `Secrets` shape:

- A registry of literal key→value pairs (today's behavior).
- A `resolve(uri)` static method that handles `password_cmd:<cmd>` (runs subprocess, returns stdout stripped) and falls back to literal for anything that doesn't start with a recognized scheme.

- [ ] **Step 1: Write the failing tests**

`tests/accountpilot/unit/core/test_auth.py`:

```python
from __future__ import annotations

import pytest

from accountpilot.core.auth import Secrets


def test_get_returns_literal_value() -> None:
    s = Secrets({"a": "literal"})
    assert s.get("a") == "literal"


def test_get_returns_none_for_missing_key() -> None:
    s = Secrets({})
    assert s.get("missing") is None


def test_get_with_default_returns_default() -> None:
    s = Secrets({})
    assert s.get("missing", "fallback") == "fallback"


def test_resolve_literal_passes_through() -> None:
    assert Secrets.resolve("plain-string") == "plain-string"


def test_resolve_password_cmd_runs_shell_and_returns_stripped_stdout() -> None:
    assert Secrets.resolve("password_cmd:echo hello") == "hello"


def test_resolve_password_cmd_strips_trailing_newline() -> None:
    assert Secrets.resolve("password_cmd:printf 'abc\\n'") == "abc"


def test_resolve_password_cmd_propagates_nonzero_exit() -> None:
    with pytest.raises(RuntimeError) as exc:
        Secrets.resolve("password_cmd:false")
    assert "exit" in str(exc.value).lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/unit/core/test_auth.py -v
```

Expected: 4 of 7 tests fail (literal/get-default/missing pass against the SP0 dataclass; the three `resolve` tests fail because the static method doesn't exist).

- [ ] **Step 3: Replace `core/auth.py` with the resolver**

`src/accountpilot/core/auth.py`:

```python
"""Credential resolution.

Two-layer model:
- `Secrets(values)` holds an in-memory key→value registry; `get(key, default)`
  matches `dict.get` semantics.
- `Secrets.resolve(uri)` recognizes the `password_cmd:<shell cmd>` scheme by
  running the command and returning its stripped stdout. Anything else is
  passed through as-is (literal credential).

SP3 will extend `resolve` to recognize `op://...` 1Password URIs natively;
for SP1, callers wrap that as `password_cmd:op read op://...` so a single
resolution path handles everything.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

_CMD_SCHEME = "password_cmd:"


@dataclass(frozen=True)
class Secrets:
    """In-memory credential registry plus a static URI resolver."""

    values: dict[str, str]

    def get(self, key: str, default: str | None = None) -> str | None:
        """Return the value registered for `key`, or `default` if absent."""
        return self.values.get(key, default)

    @staticmethod
    def resolve(uri: str) -> str:
        """Resolve a credential URI to its plaintext value.

        - `password_cmd:<shell cmd>`: run the command via the shell, return
          stripped stdout. Non-zero exit raises RuntimeError with stderr.
        - anything else: return unchanged (treated as a literal credential).
        """
        if not uri.startswith(_CMD_SCHEME):
            return uri
        cmd = uri[len(_CMD_SCHEME):]
        try:
            result = subprocess.run(  # noqa: S602 — intentional shell exec
                cmd,
                shell=True,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(
                f"password_cmd timed out after 30s: {shlex.quote(cmd)}"
            ) from e
        if result.returncode != 0:
            raise RuntimeError(
                f"password_cmd exit {result.returncode}: "
                f"{shlex.quote(cmd)}\nstderr: {result.stderr.strip()}"
            )
        return result.stdout.strip()
```

- [ ] **Step 4: Run all tests pass**

```bash
pytest tests/accountpilot/unit/core/test_auth.py tests/accountpilot/unit/core/test_plugin_base.py -v
```

Expected: 7 + existing plugin_base tests passing.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/auth.py tests/accountpilot/unit/core/test_auth.py
git commit -m "$(cat <<'EOF'
feat(core/auth): real Secrets.resolve with password_cmd: scheme

Replace SP0's dict-only Secrets stub with a resolver that handles
`password_cmd:<shell cmd>` URIs by running the command and returning
its stripped stdout. The literal-string fallback keeps existing
in-memory key/value uses working unchanged.

The mail plugin (Task 12) calls Secrets.resolve(account.credentials_ref)
to get the IMAP password just before connecting. SP3 will add native
op:// recognition; for SP1 callers wrap as `password_cmd:op read op://...`
so the single resolution path covers both.
EOF
)"
```

---

### Task 3: `upsert_owner` — auto-merge cross-person collisions

**Files:**
- Modify: `src/accountpilot/core/storage.py`
- Modify: `tests/accountpilot/unit/core/test_storage_helpers.py`

Per the SP0 final review: today, `upsert_owner` returns the first matched person and silently leaves any other-person matches dangling. SP1's setup flow with real Gmail data will hit this. Fix: when the lookup loop finds a second match pointing at a different existing person, run `merge_people` to consolidate them all under the first match before returning.

- [ ] **Step 1: Write the failing test**

Append to `tests/accountpilot/unit/core/test_storage_helpers.py`:

```python
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
        "SELECT person_id FROM identifiers WHERE value IN ('aren@x.com', '+15551234567')"
    ) as cur:
        rows = [r["person_id"] for r in await cur.fetchall()]
    assert set(rows) == {pid}
    # And the duplicate person row is gone.
    async with tmp_db.execute(
        "SELECT COUNT(*) AS c FROM people"
    ) as cur:
        assert (await cur.fetchone())["c"] == 1
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/unit/core/test_storage_helpers.py::test_upsert_owner_auto_merges_cross_person_collision -v
```

Expected: failure — currently `upsert_owner` returns the first match and the second person row is still present.

- [ ] **Step 3: Modify `upsert_owner` in `src/accountpilot/core/storage.py`**

Replace the existing existing-person-branch loop (the `for ident in identifiers:` block that does the lookup) with one that collects ALL matched person ids and consolidates them.

Specifically, replace the block currently starting `for ident in identifiers:` (around the line with `SELECT person_id FROM identifiers WHERE kind=? AND value=?` inside `upsert_owner`) with:

```python
        # Resolve every supplied identifier. matched_ids is the set of person
        # ids that already own one of these identifiers (zero, one, or many).
        matched_ids: list[int] = []
        for ident in identifiers:
            async with self.db.execute(
                "SELECT person_id FROM identifiers WHERE kind=? AND value=?",
                (ident.kind, _normalize_for_kind(ident.kind, ident.value)),
            ) as cur:
                row = await cur.fetchone()
            if row is not None:
                pid = int(row["person_id"])
                if pid not in matched_ids:
                    matched_ids.append(pid)

        if matched_ids:
            keep_id = matched_ids[0]
            # If multiple existing people match, merge them all into the first.
            for stray_id in matched_ids[1:]:
                await merge_people(self.db, keep_id=keep_id, discard_id=stray_id)

            # Promote keep_id to owner; refresh name/surname.
            await self.db.execute(
                "UPDATE people SET is_owner=1, name=?, surname=?, updated_at=? "
                "WHERE id=?",
                (name, surname, datetime.now(UTC).isoformat(), keep_id),
            )
            # Attach any not-yet-present identifiers to keep_id.
            for ident in identifiers:
                await self.db.execute(
                    "INSERT OR IGNORE INTO identifiers "
                    "(person_id, kind, value, is_primary, created_at) "
                    "VALUES (?, ?, ?, 0, ?)",
                    (keep_id, ident.kind,
                     _normalize_for_kind(ident.kind, ident.value),
                     datetime.now(UTC).isoformat()),
                )
            await self.db.commit()
            return keep_id
```

The no-match branch (creating a new owner row + identifiers) stays unchanged below this block.

Add `merge_people` to the import line at the top of `storage.py`:

```python
from accountpilot.core.identity import find_or_create_person, merge_people
```

(`find_or_create_person` is already imported.)

- [ ] **Step 4: Run all storage tests pass**

```bash
pytest tests/accountpilot/unit/core/test_storage_helpers.py -v
```

Expected: all storage helper tests pass, including the new collision test.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/storage.py tests/accountpilot/unit/core/test_storage_helpers.py
git commit -m "$(cat <<'EOF'
fix(core/storage): upsert_owner auto-merges cross-person collisions

Per AP-SP0 final review: when two identifiers in an upsert_owner call
already point at two different existing people, consolidate them via
merge_people instead of silently returning the first match and leaving
the rest dangling. This is the expected scenario for setup() flows
where contacts auto-created during save_email later get re-declared as
the same owner.

Promotion to is_owner=1 and identifier attachment happen on the
post-merge keep_id, so the result is a single owner row owning all the
declared identifiers.
EOF
)"
```

---

### Task 4: `Storage.latest_imap_uid` helper

**Files:**
- Modify: `src/accountpilot/core/storage.py`
- Modify: `tests/accountpilot/unit/core/test_storage_helpers.py`

The mail plugin's sync needs to know "what's the highest IMAP UID I've already ingested for this account, in this mailbox?" so it can resume backfill efficiently. SP0's `latest_external_id` returns the Message-ID; for IMAP UID we need a small dedicated helper.

Without this, the mail plugin would either always fetch UID 1:* (slow but correct due to dedup) or have to bypass the Storage façade. Add the helper.

- [ ] **Step 1: Write the failing test**

Append to `tests/accountpilot/unit/core/test_storage_helpers.py`:

```python
async def test_latest_imap_uid_returns_max_per_account_and_mailbox(
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
    assert await storage.latest_imap_uid(account_id, "INBOX") is None

    def _email(uid: int, ext_id: str, mailbox: str = "INBOX") -> EmailMessage:
        return EmailMessage(
            account_id=account_id, external_id=ext_id,
            sent_at=datetime(2026, 5, 1, tzinfo=UTC), received_at=None,
            direction="inbound", from_address="z@z",
            to_addresses=[], cc_addresses=[], bcc_addresses=[],
            subject="", body_text="", body_html=None, in_reply_to=None,
            references=[], imap_uid=uid, mailbox=mailbox,
            gmail_thread_id=None, labels=[], raw_headers={}, attachments=[],
        )

    await storage.save_email(_email(10, "a"))
    await storage.save_email(_email(11, "b"))
    await storage.save_email(_email(99, "c", mailbox="[Gmail]/Sent Mail"))
    assert await storage.latest_imap_uid(account_id, "INBOX") == 11
    assert await storage.latest_imap_uid(account_id, "[Gmail]/Sent Mail") == 99
    assert await storage.latest_imap_uid(account_id, "Trash") is None
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/unit/core/test_storage_helpers.py::test_latest_imap_uid_returns_max_per_account_and_mailbox -v
```

Expected: AttributeError on `Storage.latest_imap_uid`.

- [ ] **Step 3: Add `latest_imap_uid` to `Storage` in `src/accountpilot/core/storage.py`**

After `latest_sent_at`, append:

```python
    async def latest_imap_uid(
        self, account_id: int, mailbox: str
    ) -> int | None:
        """Highest imap_uid already ingested for this account+mailbox combo."""
        async with self.db.execute(
            "SELECT MAX(ed.imap_uid) AS u "
            "FROM email_details ed "
            "JOIN messages m ON m.id = ed.message_id "
            "WHERE m.account_id = ? AND ed.mailbox = ?",
            (account_id, mailbox),
        ) as cur:
            row = await cur.fetchone()
        if row is None or row["u"] is None:
            return None
        return int(row["u"])
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/unit/core/test_storage_helpers.py -v
```

Expected: all passing including the new test.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/core/storage.py tests/accountpilot/unit/core/test_storage_helpers.py
git commit -m "$(cat <<'EOF'
feat(core/storage): add latest_imap_uid helper

Mail plugin's sync needs a per-account, per-mailbox IMAP UID watermark
so it can resume backfill efficiently. Returns the MAX(email_details.imap_uid)
joined to messages.account_id where mailbox matches; None for fresh accounts
or unknown mailboxes.

Plugins still cannot SELECT directly — this preserves the SP0 invariant
that arbitrary read paths go through explicit Storage methods.
EOF
)"
```

---

### Task 5: Port `providers/` package

**Files:**
- Create: `src/accountpilot/plugins/mail/__init__.py`
- Create: `src/accountpilot/plugins/mail/providers/__init__.py`
- Create: `src/accountpilot/plugins/mail/providers/gmail.py`
- Create: `src/accountpilot/plugins/mail/providers/outlook.py`

The provider abstraction holds Gmail-/Outlook-specific IMAP folder aliases and host metadata. Pure data class hierarchy; no business logic. Move it as-is.

- [ ] **Step 1: Create the new package marker files**

`src/accountpilot/plugins/mail/__init__.py`:

```python
"""AccountPilot mail plugin — IMAP sync, RFC822 parsing, IDLE."""
```

`src/accountpilot/plugins/mail/providers/__init__.py`:

Copy the contents of `src/mailpilot/providers/__init__.py` verbatim. Then update internal imports — change `from mailpilot.providers` references (if any) to `from accountpilot.plugins.mail.providers`.

- [ ] **Step 2: Copy provider files**

```bash
cp src/mailpilot/providers/gmail.py src/accountpilot/plugins/mail/providers/gmail.py
cp src/mailpilot/providers/outlook.py src/accountpilot/plugins/mail/providers/outlook.py
```

Then in each new file, replace import paths:

In `src/accountpilot/plugins/mail/providers/gmail.py`:
```python
from accountpilot.plugins.mail.providers import Provider   # WAS: from mailpilot.providers import Provider
```

In `src/accountpilot/plugins/mail/providers/outlook.py`:
```python
from accountpilot.plugins.mail.providers import Provider   # WAS: from mailpilot.providers import Provider
```

- [ ] **Step 3: Verify importable**

```bash
python -c "from accountpilot.plugins.mail.providers.gmail import GmailProvider; print(GmailProvider.name)"
python -c "from accountpilot.plugins.mail.providers.outlook import OutlookProvider; print(OutlookProvider.name)"
```

Expected: `gmail` and `outlook` printed.

- [ ] **Step 4: Verify SP0 tests still pass**

```bash
pytest tests/accountpilot -q
ruff check src/accountpilot
mypy src/accountpilot
```

Expected: green / clean.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/plugins/mail
git commit -m "$(cat <<'EOF'
feat(plugins/mail): port providers package

Copy Gmail and Outlook provider classes from src/mailpilot/providers/
to src/accountpilot/plugins/mail/providers/, updating internal imports.
No behavior changes; the providers expose IMAP folder aliases and host
metadata used by the IMAP client.
EOF
)"
```

---

### Task 6: Port IMAP client

**Files:**
- Create: `src/accountpilot/plugins/mail/imap/__init__.py`
- Create: `src/accountpilot/plugins/mail/imap/client.py`
- Create: `tests/accountpilot/plugins/__init__.py`
- Create: `tests/accountpilot/plugins/mail/__init__.py`
- Create: `tests/accountpilot/plugins/mail/test_imap_client.py`

The async IMAP client (~500 LOC) is general-purpose and doesn't touch the DB. Move it.

- [ ] **Step 1: Copy `__init__.py` and `client.py`**

```bash
mkdir -p src/accountpilot/plugins/mail/imap
cp src/mailpilot/imap/__init__.py src/accountpilot/plugins/mail/imap/__init__.py
cp src/mailpilot/imap/client.py src/accountpilot/plugins/mail/imap/client.py
```

- [ ] **Step 2: Update imports inside the new `client.py`**

Replace any `from mailpilot.providers` with `from accountpilot.plugins.mail.providers`. Replace `from mailpilot.imap` (e.g., importing exception types from the package's `__init__.py`) with `from accountpilot.plugins.mail.imap`.

The simplest verification:

```bash
grep -n "mailpilot" src/accountpilot/plugins/mail/imap/client.py
```

Expected: zero matches after fixes.

- [ ] **Step 3: Copy and adapt the test file**

```bash
mkdir -p tests/accountpilot/plugins/mail
touch tests/accountpilot/plugins/__init__.py
touch tests/accountpilot/plugins/mail/__init__.py
cp tests/test_imap_client.py tests/accountpilot/plugins/mail/test_imap_client.py
```

In the new `tests/accountpilot/plugins/mail/test_imap_client.py`, replace any `from mailpilot.imap.client` import with `from accountpilot.plugins.mail.imap.client`. Same for `mailpilot.providers` → `accountpilot.plugins.mail.providers`.

- [ ] **Step 4: Run the ported tests**

```bash
pytest tests/accountpilot/plugins/mail/test_imap_client.py -v
```

Expected: all tests that passed under `tests/test_imap_client.py` pass under the new path.

If any fail due to test fixtures referenced from the old `tests/conftest.py`: copy the relevant fixtures into a new `tests/accountpilot/plugins/mail/conftest.py`. Don't depend on the old conftest — it's deleted in Task 16.

- [ ] **Step 5: Run all SP0+SP1 tests pass + lint clean**

```bash
pytest tests/accountpilot -q
ruff check src/accountpilot tests/accountpilot
mypy src/accountpilot
```

Expected: green / clean.

- [ ] **Step 6: Commit**

```bash
git add src/accountpilot/plugins/mail/imap tests/accountpilot/plugins
git commit -m "$(cat <<'EOF'
feat(plugins/mail): port IMAP client

Move the async IMAP client (~500 LOC, aioimaplib-based) from
src/mailpilot/imap/ to src/accountpilot/plugins/mail/imap/. Update
internal imports and migrate the matching test file. The client's
public surface (connect, disconnect, list_folders, fetch_uids,
fetch_message, fetch_headers, fetch_flags, set/remove/move/copy/
delete/append) is unchanged.
EOF
)"
```

---

### Task 7: Port IMAP IDLE listener

**Files:**
- Create: `src/accountpilot/plugins/mail/imap/idle.py`
- Create: `tests/accountpilot/plugins/mail/test_idle.py`

Same pattern as Task 6: copy + adapt imports + migrate tests. The IDLE listener (~244 LOC) wraps the IMAP IDLE loop and surfaces "new UID arrived" events.

- [ ] **Step 1: Copy and adapt**

```bash
cp src/mailpilot/imap/idle.py src/accountpilot/plugins/mail/imap/idle.py
cp tests/test_idle.py tests/accountpilot/plugins/mail/test_idle.py
```

In `src/accountpilot/plugins/mail/imap/idle.py`:
- Replace `from mailpilot.imap.client` → `from accountpilot.plugins.mail.imap.client`.
- Replace any `from mailpilot.imap` (root) → `from accountpilot.plugins.mail.imap`.

In `tests/accountpilot/plugins/mail/test_idle.py`:
- Replace `from mailpilot.imap.idle` → `from accountpilot.plugins.mail.imap.idle`.
- Adapt any other mailpilot imports.

```bash
grep -n "mailpilot" src/accountpilot/plugins/mail/imap/idle.py tests/accountpilot/plugins/mail/test_idle.py
```

Expected: zero matches.

- [ ] **Step 2: Run ported tests**

```bash
pytest tests/accountpilot/plugins/mail/test_idle.py -v
```

Expected: tests that passed under the old path pass here.

- [ ] **Step 3: Verify everything green**

```bash
pytest tests/accountpilot -q
ruff check src/accountpilot tests/accountpilot
mypy src/accountpilot
```

- [ ] **Step 4: Commit**

```bash
git add src/accountpilot/plugins/mail/imap/idle.py tests/accountpilot/plugins/mail/test_idle.py
git commit -m "$(cat <<'EOF'
feat(plugins/mail): port IMAP IDLE listener

Move IdleListener from src/mailpilot/imap/idle.py to
src/accountpilot/plugins/mail/imap/idle.py. Update internal imports
and migrate the matching test. The listener's contract is unchanged:
wrap an IMAP connection in IDLE mode and surface new-UID notifications
to the caller.
EOF
)"
```

---

### Task 8: Port OAuth helper

**Files:**
- Create: `src/accountpilot/plugins/mail/oauth.py`

The OAuth module (~163 LOC, msal-based) handles XOAUTH2 token acquisition. Copy + adapt imports. No tests in the existing repo specifically covered it (the tests for OAuth flow are integration-only); no test migration needed.

- [ ] **Step 1: Copy and adapt**

```bash
cp src/mailpilot/oauth.py src/accountpilot/plugins/mail/oauth.py
```

In `src/accountpilot/plugins/mail/oauth.py`:
- Replace `from mailpilot.config` → `from accountpilot.plugins.mail.config` (Task 10 will add the local config module).
- Replace any other `from mailpilot.*` → corresponding `from accountpilot.plugins.mail.*` if applicable.

```bash
grep -n "mailpilot" src/accountpilot/plugins/mail/oauth.py
```

Expected: zero matches. If `mailpilot.config` is referenced and Task 10 hasn't shipped yet, leave the reference as a string-literal forward reference for now and let Task 10 finalize. To be concrete, change the import to a guarded form:

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from accountpilot.plugins.mail.config import MailAccountConfig
```

so the file imports cleanly even before Task 10 lands the config module. Replace runtime usages of `MailAccountConfig` with their string-form annotations inside function signatures (`def f(account: "MailAccountConfig"): ...`).

- [ ] **Step 2: Verify importable**

```bash
python -c "import accountpilot.plugins.mail.oauth"
```

Expected: clean import.

- [ ] **Step 3: Lint + types clean**

```bash
ruff check src/accountpilot
mypy src/accountpilot
```

- [ ] **Step 4: Commit**

```bash
git add src/accountpilot/plugins/mail/oauth.py
git commit -m "$(cat <<'EOF'
feat(plugins/mail): port OAuth helper

Move msal-based XOAUTH2 token acquisition from src/mailpilot/oauth.py
to src/accountpilot/plugins/mail/oauth.py. Adapts internal imports;
the public surface (acquire_token_interactive, get_access_token) is
unchanged.

SP1 uses password_cmd auth as primary; OAuth is here for the few
accounts (Outlook, Microsoft 365) that require it. SP3's auth refresh
work will integrate this module with the Secrets resolver more
deeply.
EOF
)"
```

---

### Task 9: New typed RFC822 parser

**Files:**
- Create: `src/accountpilot/plugins/mail/parser.py`
- Create: `tests/accountpilot/plugins/mail/test_parser.py`

The mailpilot parser returns `dict[str, Any]`; we replace it with a parser that returns a fully typed `EmailMessage`. Reuse the parsing primitives where useful (header decoding, MIME walking, attachment extraction) but don't depend on mailpilot — the new parser is a clean implementation that uses the stdlib `email` package + `mail-parser` library (already a dep).

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/plugins/mail/test_parser.py`:

```python
from __future__ import annotations

from datetime import UTC, datetime

from accountpilot.plugins.mail.parser import parse_rfc822_to_email_message


_SAMPLE_RFC822 = b"""Message-ID: <abc-123@example.com>
Date: Fri, 01 May 2026 12:00:00 +0000
From: "Foo Bar" <foo@example.com>
To: aren@example.com
Cc: cc@example.com
Subject: Hello
References: <ref1@example.com> <ref2@example.com>
In-Reply-To: <ref2@example.com>
MIME-Version: 1.0
Content-Type: text/plain; charset=utf-8

Body text here.
"""


def test_parse_minimum_email() -> None:
    msg = parse_rfc822_to_email_message(
        raw_bytes=_SAMPLE_RFC822,
        account_id=1,
        mailbox="INBOX",
        imap_uid=42,
        direction="inbound",
        gmail_thread_id=None,
        labels=[],
    )
    assert msg.account_id == 1
    assert msg.imap_uid == 42
    assert msg.mailbox == "INBOX"
    assert msg.direction == "inbound"
    assert msg.external_id == "<abc-123@example.com>"
    assert msg.from_address == '"Foo Bar" <foo@example.com>'
    assert msg.to_addresses == ["aren@example.com"]
    assert msg.cc_addresses == ["cc@example.com"]
    assert msg.subject == "Hello"
    assert msg.body_text.strip() == "Body text here."
    assert msg.in_reply_to == "<ref2@example.com>"
    assert msg.references == ["<ref1@example.com>", "<ref2@example.com>"]
    assert msg.sent_at == datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
    assert msg.attachments == []


def test_parse_email_with_attachment() -> None:
    raw = (
        b"Message-ID: <att-1@x>\n"
        b"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        b"From: a@b\n"
        b"To: c@d\n"
        b"Subject: Att\n"
        b"MIME-Version: 1.0\n"
        b'Content-Type: multipart/mixed; boundary="BOUND"\n'
        b"\n"
        b"--BOUND\n"
        b"Content-Type: text/plain\n"
        b"\n"
        b"text body\n"
        b"--BOUND\n"
        b"Content-Type: application/octet-stream\n"
        b'Content-Disposition: attachment; filename="hi.bin"\n'
        b"Content-Transfer-Encoding: base64\n"
        b"\n"
        b"aGVsbG8=\n"
        b"--BOUND--\n"
    )
    msg = parse_rfc822_to_email_message(
        raw_bytes=raw, account_id=1, mailbox="INBOX",
        imap_uid=43, direction="inbound",
        gmail_thread_id=None, labels=[],
    )
    assert len(msg.attachments) == 1
    a = msg.attachments[0]
    assert a.filename == "hi.bin"
    assert a.content == b"hello"
    assert a.mime_type == "application/octet-stream"


def test_parse_propagates_raw_headers() -> None:
    msg = parse_rfc822_to_email_message(
        raw_bytes=_SAMPLE_RFC822, account_id=1, mailbox="INBOX",
        imap_uid=42, direction="inbound",
        gmail_thread_id=None, labels=[],
    )
    assert msg.raw_headers["Subject"] == "Hello"
    assert "abc-123" in msg.raw_headers["Message-ID"]
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/mail/test_parser.py -v
```

Expected: ImportError on `accountpilot.plugins.mail.parser`.

- [ ] **Step 3: Implement the parser**

`src/accountpilot/plugins/mail/parser.py`:

```python
"""RFC822 bytes → typed EmailMessage."""

from __future__ import annotations

import email
from email import policy
from email.message import EmailMessage as StdlibEmailMessage
from email.utils import parsedate_to_datetime
from typing import Literal

from accountpilot.core.models import AttachmentBlob, EmailMessage


def parse_rfc822_to_email_message(
    *,
    raw_bytes: bytes,
    account_id: int,
    mailbox: str,
    imap_uid: int,
    direction: Literal["inbound", "outbound"],
    gmail_thread_id: str | None,
    labels: list[str],
) -> EmailMessage:
    """Parse RFC822 bytes into an EmailMessage Pydantic model.

    Caller supplies envelope metadata (account, mailbox, uid, direction,
    Gmail-specific labels/thread); this parser extracts content from the
    bytes themselves.
    """
    parsed: StdlibEmailMessage = email.message_from_bytes(  # type: ignore[assignment]
        raw_bytes, policy=policy.default
    )

    external_id = (parsed.get("Message-ID") or "").strip() or f"uid-{imap_uid}"
    sent_at = _parse_date(parsed.get("Date"))
    received_at = sent_at  # IMAP doesn't surface a separate received_at via headers in v1

    body_text, body_html, attachments = _walk_parts(parsed)

    return EmailMessage(
        account_id=account_id,
        external_id=external_id,
        sent_at=sent_at,
        received_at=received_at,
        direction=direction,
        from_address=str(parsed.get("From", "")).strip(),
        to_addresses=_split_address_list(parsed.get_all("To")),
        cc_addresses=_split_address_list(parsed.get_all("Cc")),
        bcc_addresses=_split_address_list(parsed.get_all("Bcc")),
        subject=str(parsed.get("Subject", "")).strip(),
        body_text=body_text,
        body_html=body_html,
        in_reply_to=_strip_or_none(parsed.get("In-Reply-To")),
        references=_split_message_id_list(parsed.get("References")),
        imap_uid=imap_uid,
        mailbox=mailbox,
        gmail_thread_id=gmail_thread_id,
        labels=labels,
        raw_headers={k: str(v) for k, v in parsed.items()},
        attachments=attachments,
    )


def _parse_date(raw: str | None):
    """RFC2822 → tz-aware datetime. Falls back to epoch UTC if unparseable."""
    from datetime import UTC, datetime
    if not raw:
        return datetime(1970, 1, 1, tzinfo=UTC)
    try:
        dt = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return datetime(1970, 1, 1, tzinfo=UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _strip_or_none(v: object) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _split_address_list(headers: list | None) -> list[str]:
    if not headers:
        return []
    out: list[str] = []
    for h in headers:
        for addr in str(h).split(","):
            a = addr.strip()
            if a:
                out.append(a)
    return out


def _split_message_id_list(raw: object) -> list[str]:
    """References / In-Reply-To header → list of <message-id> tokens."""
    if raw is None:
        return []
    return [tok for tok in str(raw).split() if tok.startswith("<") and tok.endswith(">")]


def _walk_parts(
    parsed: StdlibEmailMessage,
) -> tuple[str, str | None, list[AttachmentBlob]]:
    body_text: str = ""
    body_html: str | None = None
    attachments: list[AttachmentBlob] = []

    for part in parsed.walk():
        ctype = part.get_content_type()
        disposition = (part.get("Content-Disposition") or "").lower()

        if part.is_multipart():
            continue

        if "attachment" in disposition or part.get_filename():
            payload = part.get_payload(decode=True) or b""
            attachments.append(AttachmentBlob(
                filename=part.get_filename() or "attachment.bin",
                content=payload,
                mime_type=ctype,
            ))
            continue

        if ctype == "text/plain" and not body_text:
            payload = part.get_payload(decode=True) or b""
            body_text = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        elif ctype == "text/html" and body_html is None:
            payload = part.get_payload(decode=True) or b""
            body_html = payload.decode(part.get_content_charset() or "utf-8", errors="replace")

    return body_text, body_html, attachments
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/plugins/mail/test_parser.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/plugins/mail/parser.py tests/accountpilot/plugins/mail/test_parser.py
git commit -m "$(cat <<'EOF'
feat(plugins/mail): typed RFC822 parser

Add parse_rfc822_to_email_message that consumes raw IMAP bytes plus
envelope metadata (account_id, mailbox, imap_uid, direction, Gmail
thread/labels) and returns a fully-typed EmailMessage Pydantic model.

Replaces mailpilot's dict-returning parser. Headers are flattened,
addresses split by comma, References tokenized to <id> tokens,
attachments decoded into AttachmentBlob via the stdlib email
package's policy.default. Body text/html extracted from the first
text/plain and text/html parts respectively.
EOF
)"
```

---

### Task 10: Mail plugin config models

**Files:**
- Create: `src/accountpilot/plugins/mail/config.py`
- Create: `tests/accountpilot/plugins/mail/test_config.py`

Plugin-specific Pydantic models that parse the `plugins.mail` block of the global `config.yaml`. SP0's `PluginConfig.extra: dict[str, Any]` was the escape hatch; this task gives it real shape.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/plugins/mail/test_config.py`:

```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from accountpilot.plugins.mail.config import (
    MailAccountConfig,
    MailPluginConfig,
)


def test_account_minimum_fields() -> None:
    a = MailAccountConfig(
        identifier="aren@example.com",
        owner="aren@example.com",
        provider="gmail",
        credentials_ref="password_cmd:op read op://Personal/gmail/password",
    )
    assert a.identifier == "aren@example.com"
    assert a.provider == "gmail"
    assert a.auth_method == "password"


def test_account_oauth_method() -> None:
    a = MailAccountConfig(
        identifier="aren@outlook.com",
        owner="aren@outlook.com",
        provider="outlook",
        auth_method="oauth",
        credentials_ref=None,
    )
    assert a.auth_method == "oauth"


def test_account_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError):
        MailAccountConfig(
            identifier="x@y", owner="x@y",
            provider="aol",  # type: ignore[arg-type]
            credentials_ref=None,
        )


def test_plugin_default_idle_timeout() -> None:
    cfg = MailPluginConfig(accounts=[])
    assert cfg.idle_timeout_seconds == 1740   # ~29 min, just below RFC's 30
    assert cfg.batch_size == 100


def test_plugin_overrides() -> None:
    cfg = MailPluginConfig(
        accounts=[],
        idle_timeout_seconds=600,
        batch_size=50,
    )
    assert cfg.idle_timeout_seconds == 600
    assert cfg.batch_size == 50
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/mail/test_config.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

`src/accountpilot/plugins/mail/config.py`:

```python
"""Mail-plugin-specific config models.

The global config loader (accountpilot.core.config) hands the `plugins.mail`
sub-tree to MailPluginConfig.model_validate(...). This module owns the
mail-specific shape; the global loader stays source-agnostic.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


MailProvider = Literal["gmail", "outlook", "imap-generic"]
MailAuthMethod = Literal["password", "oauth"]


class MailAccountConfig(_StrictBase):
    identifier: str
    owner: str
    provider: MailProvider
    auth_method: MailAuthMethod = "password"
    credentials_ref: str | None = None
    # OAuth-specific (only meaningful when auth_method='oauth'):
    oauth_client_id: str | None = None
    oauth_tenant: str | None = None


class MailPluginConfig(_StrictBase):
    accounts: list[MailAccountConfig] = []
    idle_timeout_seconds: int = 1740   # ~29 min; IMAP RFC requires <30
    batch_size: int = 100              # how many UIDs to fetch per chunk
```

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/plugins/mail/test_config.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/plugins/mail/config.py tests/accountpilot/plugins/mail/test_config.py
git commit -m "$(cat <<'EOF'
feat(plugins/mail): config models for mail plugin

MailAccountConfig and MailPluginConfig give the `plugins.mail` block of
config.yaml a typed shape. Provider literal: gmail | outlook |
imap-generic. Auth method: password (default, uses Secrets.resolve on
credentials_ref) or oauth (uses ported oauth.py).

idle_timeout_seconds default 1740 sits just under the IMAP RFC's
30-minute IDLE limit. batch_size default 100 controls the IMAP UID
chunk fetched per backfill round-trip.
EOF
)"
```

---

### Task 11: Sync orchestrator

**Files:**
- Create: `src/accountpilot/plugins/mail/sync.py`
- Create: `tests/accountpilot/plugins/mail/conftest.py`
- Create: `tests/accountpilot/plugins/mail/test_sync.py`

The orchestrator: given a connected `ImapClient` + an `account_id`, fetch UIDs above the latest watermark, parse each, call `Storage.save_email`. Returns a count summary.

- [ ] **Step 1: Write the FakeImapClient fixture**

`tests/accountpilot/plugins/mail/conftest.py`:

```python
"""Mail-plugin test fixtures: FakeImapClient for sync/plugin tests."""

from __future__ import annotations

import pytest


class FakeImapClient:
    """In-memory IMAP stand-in for sync orchestrator tests.

    Holds a mailbox→[(uid, raw_bytes)] map and exposes the subset of
    ImapClient methods sync.py uses.
    """

    def __init__(self, mailbox_data: dict[str, list[tuple[int, bytes]]]) -> None:
        self._data = mailbox_data
        self.connected_to: str | None = None

    async def connect(self, folder: str = "INBOX") -> None:
        self.connected_to = folder

    async def disconnect(self, folder: str | None = None) -> None:
        self.connected_to = None

    async def fetch_uids(self, folder: str, *, since_uid: int = 0) -> list[int]:
        return [u for (u, _) in self._data.get(folder, []) if u > since_uid]

    async def fetch_message(self, folder: str, uid: int) -> bytes:
        for (u, raw) in self._data.get(folder, []):
            if u == uid:
                return raw
        raise KeyError(f"uid {uid} not in {folder}")


@pytest.fixture
def sample_rfc822() -> bytes:
    return (
        b"Message-ID: <synth-{uid}@example.com>\n"
        b"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        b"From: Foo <foo@example.com>\n"
        b"To: aren@example.com\n"
        b"Subject: Test {uid}\n"
        b"MIME-Version: 1.0\n"
        b"Content-Type: text/plain; charset=utf-8\n"
        b"\n"
        b"body {uid}\n"
    )


def make_rfc822(uid: int) -> bytes:
    return (
        f"Message-ID: <synth-{uid}@example.com>\n"
        f"Date: Fri, 01 May 2026 12:00:00 +0000\n"
        "From: Foo <foo@example.com>\n"
        "To: aren@example.com\n"
        f"Subject: Test {uid}\n"
        "MIME-Version: 1.0\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        f"body {uid}\n"
    ).encode()
```

- [ ] **Step 2: Write the failing sync test**

`tests/accountpilot/plugins/mail/test_sync.py`:

```python
from __future__ import annotations

from pathlib import Path

import aiosqlite

from accountpilot.core.cas import CASStore
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage
from accountpilot.plugins.mail.sync import sync_account_mailbox
from tests.accountpilot.plugins.mail.conftest import FakeImapClient, make_rfc822


async def _seed_account(storage: Storage) -> int:
    owner = await storage.upsert_owner(
        name="Aren", surname=None,
        identifiers=[Identifier(kind="email", value="aren@example.com")],
    )
    return await storage.upsert_account(
        source="gmail", identifier="aren@example.com", owner_id=owner,
    )


async def test_sync_inserts_new_messages(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        account_id = await _seed_account(storage)
        imap = FakeImapClient({
            "INBOX": [(1, make_rfc822(1)), (2, make_rfc822(2))],
        })

        result = await sync_account_mailbox(
            storage=storage, imap=imap,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )
        assert result.inserted == 2
        assert result.skipped == 0

        # Re-running picks up nothing new (dedup).
        result2 = await sync_account_mailbox(
            storage=storage, imap=imap,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )
        assert result2.inserted == 0
        assert result2.skipped == 0   # all UIDs are <= watermark, nothing fetched


async def test_sync_resumes_from_watermark(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        account_id = await _seed_account(storage)

        # Round 1: UIDs 1-2.
        imap = FakeImapClient({"INBOX": [(1, make_rfc822(1)), (2, make_rfc822(2))]})
        await sync_account_mailbox(
            storage=storage, imap=imap,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )

        # Round 2: server now has 1-4. Plugin should fetch only 3, 4.
        imap2 = FakeImapClient({"INBOX": [
            (1, make_rfc822(1)), (2, make_rfc822(2)),
            (3, make_rfc822(3)), (4, make_rfc822(4)),
        ]})
        result = await sync_account_mailbox(
            storage=storage, imap=imap2,
            account_id=account_id, mailbox="INBOX",
            gmail_thread_resolver=None, labels=[],
        )
        assert result.inserted == 2

        async with db.execute("SELECT COUNT(*) AS c FROM messages") as cur:
            assert (await cur.fetchone())["c"] == 4
```

- [ ] **Step 3: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/mail/test_sync.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement `src/accountpilot/plugins/mail/sync.py`**

```python
"""Sync orchestrator: ImapClient + Storage → ingested rows."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from accountpilot.core.models import EmailMessage
from accountpilot.core.storage import Storage
from accountpilot.plugins.mail.parser import parse_rfc822_to_email_message


class _ImapClientProto(Protocol):
    async def fetch_uids(
        self, folder: str, *, since_uid: int = 0
    ) -> list[int]: ...
    async def fetch_message(self, folder: str, uid: int) -> bytes: ...


@dataclass(frozen=True)
class SyncResult:
    inserted: int
    skipped: int


async def sync_account_mailbox(
    *,
    storage: Storage,
    imap: _ImapClientProto,
    account_id: int,
    mailbox: str,
    gmail_thread_resolver: Callable[[bytes], Awaitable[str | None]] | None,
    labels: list[str],
) -> SyncResult:
    """Fetch new UIDs from `imap`, parse, and persist via `storage.save_email`.

    Resumes from `Storage.latest_imap_uid(account_id, mailbox)`. Re-running is
    safe: the IMAP UID watermark advances monotonically and Storage dedupes by
    `(account_id, external_id)` regardless.
    """
    watermark = await storage.latest_imap_uid(account_id, mailbox) or 0
    uids = await imap.fetch_uids(mailbox, since_uid=watermark)
    inserted = 0
    skipped = 0

    for uid in uids:
        raw = await imap.fetch_message(mailbox, uid)
        gmail_thread_id = (
            await gmail_thread_resolver(raw) if gmail_thread_resolver else None
        )
        msg: EmailMessage = parse_rfc822_to_email_message(
            raw_bytes=raw,
            account_id=account_id,
            mailbox=mailbox,
            imap_uid=uid,
            direction="inbound",
            gmail_thread_id=gmail_thread_id,
            labels=list(labels),
        )
        result = await storage.save_email(msg)
        if result.action == "inserted":
            inserted += 1
        elif result.action == "skipped":
            skipped += 1

    return SyncResult(inserted=inserted, skipped=skipped)
```

- [ ] **Step 5: Run tests pass**

```bash
pytest tests/accountpilot/plugins/mail/test_sync.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/accountpilot/plugins/mail/sync.py tests/accountpilot/plugins/mail/conftest.py tests/accountpilot/plugins/mail/test_sync.py
git commit -m "$(cat <<'EOF'
feat(plugins/mail): sync orchestrator

sync_account_mailbox(storage, imap, account_id, mailbox, …) reads the
imap UID watermark from Storage, fetches new UIDs via the imap client,
parses each into an EmailMessage, and persists via storage.save_email.
Returns a SyncResult(inserted, skipped) summary.

The imap argument is structurally typed (Protocol) so production uses
ImapClient and tests use FakeImapClient.

Idempotent: dedup happens both at the IMAP-UID layer (watermark filter)
and at the Storage layer (UNIQUE on account_id+external_id).
EOF
)"
```

---

### Task 12: `MailPlugin` — 5 lifecycle hooks

**Files:**
- Create: `src/accountpilot/plugins/mail/plugin.py`
- Create: `tests/accountpilot/plugins/mail/test_plugin.py`

Implements the `AccountPilotPlugin` ABC. Wires together: config → ImapClient → IDLE → sync orchestrator. Tests cover the lifecycle with FakeImap (no real network).

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/plugins/mail/test_plugin.py`:

```python
from __future__ import annotations

from pathlib import Path

import aiosqlite

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.db.connection import open_db
from accountpilot.core.models import Identifier
from accountpilot.core.storage import Storage
from accountpilot.plugins.mail.config import MailAccountConfig, MailPluginConfig
from accountpilot.plugins.mail.plugin import MailPlugin
from tests.accountpilot.plugins.mail.conftest import FakeImapClient, make_rfc822


async def test_mail_plugin_sync_once_ingests(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        owner = await storage.upsert_owner(
            name="Aren", surname=None,
            identifiers=[Identifier(kind="email", value="aren@example.com")],
        )
        account_id = await storage.upsert_account(
            source="gmail", identifier="aren@example.com", owner_id=owner,
        )

        cfg = MailPluginConfig(
            accounts=[
                MailAccountConfig(
                    identifier="aren@example.com",
                    owner="aren@example.com",
                    provider="gmail",
                    credentials_ref="literal-pw",
                )
            ],
        )
        fake = FakeImapClient({"INBOX": [(1, make_rfc822(1))]})

        plugin = MailPlugin(
            config=cfg.model_dump(),
            storage=storage,
            secrets=Secrets({}),
        )
        # Inject the fake at the connection-factory seam.
        plugin._imap_factory = lambda account: fake  # type: ignore[attr-defined]

        await plugin.setup()
        await plugin.sync_once(account_id)

        async with db.execute("SELECT COUNT(*) AS c FROM messages") as cur:
            assert (await cur.fetchone())["c"] == 1


async def test_mail_plugin_backfill_calls_sync_once(
    tmp_db_path: Path, tmp_runtime: Path
) -> None:
    async with open_db(tmp_db_path) as db:
        storage = Storage(db, CASStore(tmp_runtime / "attachments"))
        owner = await storage.upsert_owner(
            name="Aren", surname=None,
            identifiers=[Identifier(kind="email", value="aren@example.com")],
        )
        account_id = await storage.upsert_account(
            source="gmail", identifier="aren@example.com", owner_id=owner,
        )

        cfg = MailPluginConfig(accounts=[MailAccountConfig(
            identifier="aren@example.com", owner="aren@example.com",
            provider="gmail", credentials_ref="literal-pw",
        )])
        fake = FakeImapClient({"INBOX": [(i, make_rfc822(i)) for i in range(1, 6)]})
        plugin = MailPlugin(config=cfg.model_dump(), storage=storage, secrets=Secrets({}))
        plugin._imap_factory = lambda account: fake  # type: ignore[attr-defined]

        await plugin.setup()
        await plugin.backfill(account_id)

        async with db.execute("SELECT COUNT(*) AS c FROM messages") as cur:
            assert (await cur.fetchone())["c"] == 5
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/mail/test_plugin.py -v
```

Expected: ImportError on `accountpilot.plugins.mail.plugin`.

- [ ] **Step 3: Implement `src/accountpilot/plugins/mail/plugin.py`**

```python
"""MailPlugin — implements the 5-hook AccountPilotPlugin contract for mail."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any, ClassVar

from accountpilot.core.auth import Secrets
from accountpilot.core.plugin import AccountPilotPlugin
from accountpilot.plugins.mail.config import (
    MailAccountConfig,
    MailPluginConfig,
)
from accountpilot.plugins.mail.imap.client import ImapClient
from accountpilot.plugins.mail.providers import resolve_provider
from accountpilot.plugins.mail.sync import sync_account_mailbox

log = logging.getLogger(__name__)


class MailPlugin(AccountPilotPlugin):
    """Mail source plugin: IMAP fetch + IDLE."""

    name: ClassVar[str] = "mail"

    def __init__(
        self, config: dict[str, Any], storage: Any, secrets: Secrets
    ) -> None:
        super().__init__(config=config, storage=storage, secrets=secrets)
        self._cfg = MailPluginConfig.model_validate(config)
        # Map of account_identifier → MailAccountConfig for lookups.
        self._accounts: dict[str, MailAccountConfig] = {
            a.identifier: a for a in self._cfg.accounts
        }
        # Test seam: tests override to inject FakeImapClient.
        self._imap_factory = self._make_real_imap

    def _make_real_imap(self, account: MailAccountConfig) -> ImapClient:
        provider = resolve_provider(account.provider)
        password = (
            self.secrets.resolve(account.credentials_ref)
            if account.credentials_ref
            else None
        )
        return ImapClient(
            host=provider.imap_host,
            port=provider.imap_port,
            username=account.identifier,
            password=password,
            use_ssl=True,
        )

    async def _resolve_account(self, account_id: int) -> MailAccountConfig:
        """Map account_id (DB row PK) → MailAccountConfig (config.yaml entry).

        The accounts table holds the canonical identifier; the config is keyed
        by identifier. Plugins reach into self.storage.db here because there's
        no SP0 Storage helper for "give me an account row by id" (one of the
        SP1 follow-ups noted in the SP0 final review). Add such a helper in
        SP3 if more plugins need this lookup.
        """
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
                f"configured in plugins.mail.accounts in config.yaml"
            )
        return self._accounts[identifier]

    # ─── Lifecycle hooks ───────────────────────────────────────────────────

    async def setup(self) -> None:
        log.info("mail plugin setup: %d account(s) configured", len(self._accounts))

    async def backfill(
        self, account_id: int, *, since: datetime | None = None
    ) -> None:
        # SP1 backfill = full sync_once + write backfilled_at on accounts.
        await self.sync_once(account_id)
        await self._mark_backfilled(account_id)

    async def sync_once(self, account_id: int) -> None:
        account = await self._resolve_account(account_id)
        imap = self._imap_factory(account)
        try:
            await imap.connect("INBOX")
            result = await sync_account_mailbox(
                storage=self.storage, imap=imap,
                account_id=account_id, mailbox="INBOX",
                gmail_thread_resolver=None, labels=[],
            )
            log.info(
                "sync_once account=%d mailbox=INBOX inserted=%d skipped=%d",
                account_id, result.inserted, result.skipped,
            )
        finally:
            await imap.disconnect("INBOX")

    async def daemon(self, account_id: int) -> None:
        """IDLE loop: connect, IDLE, on new-uid notification → fetch + save."""
        # SP1 implements polling-style daemon: sync_once every idle_timeout.
        # AP-SP2 will swap to real IDLE listener integration.
        # Validate the account is reachable in config before entering the loop.
        await self._resolve_account(account_id)
        log.info("mail daemon starting for account=%d", account_id)
        while True:
            try:
                await self.sync_once(account_id)
            except Exception:  # noqa: BLE001
                log.exception("daemon sync_once failed; retrying in %ds",
                              self._cfg.idle_timeout_seconds)
            await asyncio.sleep(self._cfg.idle_timeout_seconds)

    async def teardown(self) -> None:
        log.info("mail plugin teardown")

    # ─── Internals ─────────────────────────────────────────────────────────

    async def _mark_backfilled(self, account_id: int) -> None:
        # Direct storage update via a Storage method that doesn't yet exist;
        # for SP1 we issue the UPDATE inline through storage.db. This is the
        # one place plugins reach into db; SP3 should add a Storage method.
        await self.storage.db.execute(
            "UPDATE accounts SET backfilled_at=? WHERE id=?",
            (datetime.now(UTC).isoformat(), account_id),
        )
        await self.storage.db.commit()
```

The `resolve_provider` helper isn't defined yet — add it to `src/accountpilot/plugins/mail/providers/__init__.py`. The provider package is the right home; expose a tiny dispatcher:

```python
# Append to src/accountpilot/plugins/mail/providers/__init__.py

from accountpilot.plugins.mail.providers.gmail import GmailProvider
from accountpilot.plugins.mail.providers.outlook import OutlookProvider


def resolve_provider(name: str) -> Provider:
    """Return the Provider instance for a given config string."""
    if name == "gmail":
        return GmailProvider()
    if name == "outlook":
        return OutlookProvider()
    raise ValueError(f"unknown provider: {name}")
```

(`Provider` is the base class already defined in this file from Task 5's port. Adjust if the actual class hierarchy differs after the port — read `src/accountpilot/plugins/mail/providers/__init__.py` first to see what the existing structure is and add `resolve_provider` accordingly.)

If `ImapClient` doesn't accept the constructor kwargs above (`host`, `port`, `username`, `password`, `use_ssl`), check the ported `ImapClient.__init__` signature in `src/accountpilot/plugins/mail/imap/client.py` and pass whatever shape it expects. The plan author surveyed only method names, not the constructor.

- [ ] **Step 4: Run tests pass**

```bash
pytest tests/accountpilot/plugins/mail/test_plugin.py -v
```

Expected: 2 passed.

If test 1 fails because `_imap_factory` doesn't exist as an attribute that tests can override, add it as a public assignment seam (the implementation above already does this).

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/plugins/mail/plugin.py src/accountpilot/plugins/mail/providers/__init__.py tests/accountpilot/plugins/mail/test_plugin.py
git commit -m "$(cat <<'EOF'
feat(plugins/mail): MailPlugin with 5 lifecycle hooks

setup, backfill, sync_once, daemon, teardown — implementing the SP0
AccountPilotPlugin contract. setup is informational; backfill calls
sync_once and marks accounts.backfilled_at; sync_once connects to IMAP
and runs sync_account_mailbox for INBOX; daemon polls in a loop with
idle_timeout_seconds spacing; teardown is a no-op.

The IDLE loop in daemon is polling-shaped for SP1; AP-SP2 will swap in
the real IdleListener integration. Polling-with-dedup is correct, just
slow on a quiet mailbox.

A `_imap_factory` attribute lets tests inject FakeImapClient without
patching at the import level. Production wires it to the real
ImapClient with provider-derived host/port and Secrets-resolved
password.

resolve_provider() in plugins/mail/providers/__init__.py dispatches
config strings ('gmail', 'outlook') to the right Provider class.
EOF
)"
```

---

### Task 13: Mail CLI subcommands

**Files:**
- Create: `src/accountpilot/plugins/mail/cli.py`
- Modify: `src/accountpilot/cli.py` (load mail plugin and register its CLI)
- Create: `tests/accountpilot/plugins/mail/test_cli.py`

`accountpilot mail backfill <account>`, `mail sync <account>`, `mail daemon`. The plugin's `cli()` returns a Click group that the root CLI registers.

- [ ] **Step 1: Write the failing test**

`tests/accountpilot/plugins/mail/test_cli.py`:

```python
from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from accountpilot.cli import cli


def test_mail_subgroup_registered() -> None:
    runner = CliRunner()
    result = runner.invoke(cli, ["mail", "--help"])
    assert result.exit_code == 0
    assert "backfill" in result.output
    assert "sync" in result.output
    assert "daemon" in result.output


def test_mail_sync_runs_against_unconfigured_db_errors_cleanly(
    tmp_db_path: Path
) -> None:
    """sync against a DB with no mail config should fail fast, not crash."""
    runner = CliRunner()
    result = runner.invoke(
        cli, ["mail", "sync", "1", "--db-path", str(tmp_db_path)],
    )
    assert result.exit_code != 0
    assert "config" in result.output.lower() or "account" in result.output.lower()
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/accountpilot/plugins/mail/test_cli.py -v
```

Expected: failure on missing `mail` subcommand.

- [ ] **Step 3: Implement `src/accountpilot/plugins/mail/cli.py`**

```python
"""accountpilot mail CLI subgroup."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import click

from accountpilot.core.auth import Secrets
from accountpilot.core.cas import CASStore
from accountpilot.core.config import load_config
from accountpilot.core.db.connection import open_db
from accountpilot.core.storage import Storage
from accountpilot.plugins.mail.plugin import MailPlugin


@click.group("mail")
def mail_group() -> None:
    """Mail plugin commands (backfill, sync, daemon)."""


def _db_option(f):
    return click.option(
        "--db-path",
        type=click.Path(path_type=Path),
        default=Path.home() / "runtime" / "accountpilot" / "accountpilot.db",
    )(f)


def _config_option(f):
    return click.option(
        "--config",
        "config_path",
        type=click.Path(path_type=Path),
        default=Path.home() / ".config" / "accountpilot" / "config.yaml",
    )(f)


@asynccontextmanager
async def _opened_plugin(
    config_path: Path, db_path: Path
) -> AsyncIterator[tuple[MailPlugin, Storage]]:
    """Open DB, build Storage + MailPlugin, yield. Closes DB on exit."""
    cfg = load_config(config_path)
    mail_cfg_raw = cfg.plugins.get("mail")
    if mail_cfg_raw is None or not mail_cfg_raw.enabled:
        raise click.UsageError(
            f"no enabled `plugins.mail` section in {config_path}"
        )
    mail_cfg_dict: dict = {
        "accounts": [a.model_dump() for a in mail_cfg_raw.accounts],
        **mail_cfg_raw.extra,
    }
    cas = CASStore(db_path.parent / "attachments")
    async with open_db(db_path) as db:
        storage = Storage(db, cas)
        plugin = MailPlugin(
            config=mail_cfg_dict, storage=storage, secrets=Secrets({})
        )
        yield plugin, storage


@mail_group.command("backfill")
@click.argument("account_id", type=int)
@_db_option
@_config_option
def mail_backfill(account_id: int, db_path: Path, config_path: Path) -> None:
    """One-shot historical pull for an account."""
    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, _):
            await plugin.setup()
            await plugin.backfill(account_id)

    asyncio.run(_run())
    click.echo(f"backfill complete: account={account_id}")


@mail_group.command("sync")
@click.argument("account_id", type=int)
@_db_option
@_config_option
def mail_sync(account_id: int, db_path: Path, config_path: Path) -> None:
    """One incremental sync pass."""
    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, _):
            await plugin.setup()
            await plugin.sync_once(account_id)

    asyncio.run(_run())
    click.echo(f"sync complete: account={account_id}")


@mail_group.command("daemon")
@_db_option
@_config_option
def mail_daemon(db_path: Path, config_path: Path) -> None:
    """Long-running daemon: polls all enabled mail accounts."""

    async def _run() -> None:
        async with _opened_plugin(config_path, db_path) as (plugin, storage):
            await plugin.setup()
            # Look up enabled mail accounts from DB.
            async with storage.db.execute(
                "SELECT id FROM accounts WHERE source='gmail' AND enabled=1"
            ) as cur:
                rows = [r["id"] for r in await cur.fetchall()]
            if not rows:
                raise click.UsageError("no enabled gmail accounts in DB")
            # Run all in parallel.
            import asyncio as _asyncio
            await _asyncio.gather(*(plugin.daemon(aid) for aid in rows))

    asyncio.run(_run())
```

- [ ] **Step 4: Register the mail CLI in `src/accountpilot/cli.py`**

Add the import and `cli.add_command(mail_group)` line:

```python
"""AccountPilot CLI root."""

import click

from accountpilot.core.cli.accounts_cmds import accounts_group
from accountpilot.core.cli.db_cmds import db_group
from accountpilot.core.cli.people_cmds import people_group
from accountpilot.core.cli.search_cmd import search_cmd
from accountpilot.core.cli.setup_cmd import setup_cmd
from accountpilot.core.cli.status_cmd import status_cmd
from accountpilot.plugins.mail.cli import mail_group


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


cli.add_command(db_group)
cli.add_command(search_cmd)
cli.add_command(status_cmd)
cli.add_command(people_group)
cli.add_command(accounts_group)
cli.add_command(setup_cmd)
cli.add_command(mail_group)
```

(The existing imports may differ slightly; preserve all existing registrations and add `mail_group`.)

- [ ] **Step 5: Run tests pass**

```bash
pytest tests/accountpilot/plugins/mail/test_cli.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add src/accountpilot/plugins/mail/cli.py src/accountpilot/cli.py tests/accountpilot/plugins/mail/test_cli.py
git commit -m "$(cat <<'EOF'
feat(plugins/mail/cli): add accountpilot mail {backfill,sync,daemon}

Three subcommands:
- `mail backfill <account_id>`: one-shot historical pull, marks
  accounts.backfilled_at on success.
- `mail sync <account_id>`: one incremental pass.
- `mail daemon`: long-running, polls all enabled gmail accounts in
  parallel until SIGTERM.

All accept --db-path and --config so tests and ad-hoc invocations can
target sandboxes. The root CLI module registers the mail subgroup
alongside db/search/status/people/accounts/setup.
EOF
)"
```

---

### Task 14: Plugin entry-point integration

**Files:**
- Modify: `src/accountpilot/cli.py` (lazy load via discover_plugins instead of hard import)

Task 1's pyproject already declared `[project.entry-points."accountpilot.plugins"] mail = "accountpilot.plugins.mail.plugin:MailPlugin"`. Task 13 hard-imports `mail_group` into the root CLI for now. This task replaces the hard import with entry-point-based discovery so the root CLI doesn't need to know about specific plugin packages — it asks `core.plugin.discover_plugins()` what's installed and registers each plugin's `cli()` group.

This is the "AccountPilot is genuinely plugin-extensible" milestone.

- [ ] **Step 1: Test that mail still works via discovery**

The existing CLI tests should keep passing. Add one test verifying discovery picks up the mail plugin:

`tests/accountpilot/unit/core/test_plugin_discovery.py`:

```python
from __future__ import annotations

from accountpilot.core.plugin import AccountPilotPlugin, discover_plugins


def test_mail_plugin_is_discoverable() -> None:
    plugins = discover_plugins()
    assert "mail" in plugins
    cls = plugins["mail"]
    assert issubclass(cls, AccountPilotPlugin)
    assert cls.name == "mail"
```

- [ ] **Step 2: Run to verify it passes already (entry point was registered in Task 1)**

```bash
pytest tests/accountpilot/unit/core/test_plugin_discovery.py -v
```

Expected: passes if `pip install -e .` was rerun after Task 1 (which it should have been). If it fails, run `pip install -e ".[dev]"` first to refresh the entry-points cache.

- [ ] **Step 3: Replace hard import with discovery loop in `src/accountpilot/cli.py`**

Replace the contents of `src/accountpilot/cli.py` with:

```python
"""AccountPilot CLI root.

Plugin-contributed subcommands are registered by iterating
`accountpilot.plugins` entry points and calling each plugin's `cli()`
classmethod (a Click group) — no hard import needed in this module.

If a plugin's class is importable but has no `cli()` group, it's
loaded for daemon/sync use but contributes no CLI subcommand.
"""

from __future__ import annotations

import click

from accountpilot.core.cli.accounts_cmds import accounts_group
from accountpilot.core.cli.db_cmds import db_group
from accountpilot.core.cli.people_cmds import people_group
from accountpilot.core.cli.search_cmd import search_cmd
from accountpilot.core.cli.setup_cmd import setup_cmd
from accountpilot.core.cli.status_cmd import status_cmd
from accountpilot.core.plugin import discover_plugins


@click.group()
@click.version_option()
def cli() -> None:
    """AccountPilot — unified account sync framework."""


cli.add_command(db_group)
cli.add_command(search_cmd)
cli.add_command(status_cmd)
cli.add_command(people_group)
cli.add_command(accounts_group)
cli.add_command(setup_cmd)


# Plugin-contributed CLI subgroups. Each plugin's `cli()` classmethod
# returns a Click group (or None if it contributes no CLI). Discovery
# happens at module import; the entry-point cache is populated by
# `pip install`.
def _register_plugin_clis() -> None:
    for _name, plugin_cls in discover_plugins().items():
        # `cli` here is a *classmethod*-style accessor on the plugin class,
        # not an instance method — for SP1 we need an instance. The mail
        # plugin exposes its CLI as a module-level Click group instead,
        # so we ask each plugin module for `cli_group` if present.
        try:
            module = __import__(plugin_cls.__module__, fromlist=["cli_group"])
            grp = getattr(module, "cli_group", None)
            if grp is None:
                # Fall back: plugin's package may live at .cli — try that.
                pkg = plugin_cls.__module__.rsplit(".", 1)[0]
                cli_module = __import__(f"{pkg}.cli", fromlist=["mail_group"])
                # The convention for SP1: each plugin's cli module exports
                # a `<name>_group`.
                grp = getattr(cli_module, f"{plugin_cls.name}_group", None)
            if grp is not None:
                cli.add_command(grp)
        except (ImportError, AttributeError):
            pass


_register_plugin_clis()
```

- [ ] **Step 4: Verify the mail subgroup still appears + all CLI tests pass**

```bash
accountpilot --help | grep -E "^  (db|search|status|people|accounts|setup|mail)"
pytest tests/accountpilot -q
```

Expected: `mail` listed in `--help` output; full SP0+SP1 suite passes.

- [ ] **Step 5: Commit**

```bash
git add src/accountpilot/cli.py tests/accountpilot/unit/core/test_plugin_discovery.py
git commit -m "$(cat <<'EOF'
feat(cli): register plugin subgroups via entry-point discovery

Replace the hard import of `mail_group` with an iteration over
`discover_plugins()` results. Each plugin module is expected to
export a `<plugin_name>_group` Click group (e.g. mail_group) which
the root CLI registers automatically.

This decouples the CLI from any specific plugin package. AP-SP2's
imessage plugin will register the same way without modifying cli.py.
EOF
)"
```

---

### Task 15: launchd plist scaffolding

**Files:**
- Create: `~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist`

A skeleton launchd job that runs `accountpilot mail daemon`. Per project convention, deployment plists live in the infra repo, not here. This task creates the file in infra; the user manually runs `launchctl bootstrap gui/$UID` to enable it.

Per the project CLAUDE.md, infra is in spec freeze; *deployment configs* are not specs and are routine. This file is a configuration artifact, fine to add.

- [ ] **Step 1: Create the plist**

`~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.accountpilot.mail.daemon</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/ae/.venv/accountpilot/bin/accountpilot</string>
        <string>mail</string>
        <string>daemon</string>
    </array>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/ae/runtime/accountpilot/logs/mail.daemon.stdout.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/ae/runtime/accountpilot/logs/mail.daemon.stderr.log</string>

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

The `ProgramArguments[0]` path assumes a venv at `~/.venv/accountpilot/`. If your install uses a different path, update accordingly. The user manually creates the venv before bootstrapping the job.

- [ ] **Step 2: Document the deploy command**

The user runs (manually, not by this task):

```bash
launchctl bootstrap gui/$UID ~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist
launchctl enable gui/$UID/com.accountpilot.mail.daemon
launchctl kickstart gui/$UID/com.accountpilot.mail.daemon
```

- [ ] **Step 3: Commit (in the infra repo)**

```bash
cd ~/Projects/infra
git add configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist
git commit -m "$(cat <<'EOF'
feat(ae/launchd): com.accountpilot.mail.daemon job

Long-running mail.daemon for AccountPilot AP-SP1. Runs `accountpilot
mail daemon` under the user agent context (`launchctl bootstrap
gui/$UID`). KeepAlive=true so launchd revives it on crash; logs
stream to ~/runtime/accountpilot/logs/.

Bootstrap manually; not yet wired into infra's deploy automation.
EOF
)"
cd /Users/ae/Code/account-pilot
```

(The plan's main commit chain is in account-pilot; this task is the only one that touches infra. Preserve that boundary.)

- [ ] **Step 4: Mark task complete**

No code changes in the account-pilot repo for this task. Commit a small docs note if you want a marker:

```bash
# (optional) — skip if no marker desired
echo "See ~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist for deploy plist." >> docs/plans/2026-05-02-accountpilot-ap-sp1.md
```

Or just move on.

---

### Task 16: Delete `src/mailpilot/` and obsolete tests

**Files:**
- Delete: `src/mailpilot/` (entire directory)
- Delete: many `tests/test_*.py` files
- Delete: `tests/conftest.py` (mailpilot-specific)
- Modify: `pyproject.toml` (remove any remaining mailpilot references)

After Tasks 5–13 ported the parts of mailpilot we keep, this task removes everything else.

**What survives** (already moved or rewritten in tasks 1–14):
- IMAP client + IDLE → `src/accountpilot/plugins/mail/imap/`
- Providers → `src/accountpilot/plugins/mail/providers/`
- OAuth → `src/accountpilot/plugins/mail/oauth.py`
- Parser → `src/accountpilot/plugins/mail/parser.py`

**What does NOT survive** (out of scope for AP v1, per spec §2 non-goals):
- `mailpilot/database.py` — replaced by `accountpilot.core.db`
- `mailpilot/search/` — Xapian replaced by FTS5
- `mailpilot/tags/` — out of scope
- `mailpilot/events/` — no event bus in AP
- `mailpilot/smtp/` — read-only in AP v1
- `mailpilot/imap/sync.py` — Maildir-based; replaced by `plugins/mail/sync.py`
- `mailpilot/{cli,config,daemon,models}.py` — replaced by `accountpilot.core.*`

- [ ] **Step 1: Remove the mailpilot package**

```bash
rm -rf src/mailpilot
```

- [ ] **Step 2: Remove obsolete tests**

```bash
rm tests/test_api.py
rm tests/test_cli.py
rm tests/test_composer.py
rm tests/test_config.py
rm tests/test_daemon.py
rm tests/test_database.py
rm tests/test_events.py
rm tests/test_idle.py
rm tests/test_imap_client.py
rm tests/test_parser.py
rm tests/test_search.py
rm tests/test_smtp.py
rm tests/test_sync.py
rm tests/test_tags.py
rm tests/test_threading.py

# tests/conftest.py — check whether anything else uses it before deleting.
# tests/__init__.py is intentionally kept (Task 1 of SP0 created it for
# tests.accountpilot.fixtures.* imports).
if [ -f tests/conftest.py ]; then
  rm tests/conftest.py
fi
```

- [ ] **Step 3: Verify pyproject is clean**

```bash
grep -n "mailpilot" pyproject.toml
```

Expected: zero matches. (Task 1 already removed package and script entries.) If anything remains, remove it.

- [ ] **Step 4: Drop any stray `mail.db` artifact**

```bash
[ -f mail.db ] && rm mail.db
[ -f ~/.mailpilot/mail.db ] && rm ~/.mailpilot/mail.db   # optional: remove user's old data store
```

The second line is destructive — only run if the user explicitly wants the legacy `~/.mailpilot/` cleaned out.

- [ ] **Step 5: Verify tests + lint clean**

```bash
pytest tests/accountpilot -q
ruff check src/accountpilot tests/accountpilot
mypy src/accountpilot
```

Expected:
- pytest: all green.
- ruff + mypy: clean.

- [ ] **Step 6: Verify no stray mailpilot references**

```bash
git grep mailpilot src/ tests/ pyproject.toml | grep -v "^docs/"
```

Expected: zero matches outside `docs/`. (The plan + spec docs reference mailpilot for historical context; that's fine.)

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
chore: delete src/mailpilot/ and obsolete tests

Per AP-SP1's design, mailpilot's parts that AccountPilot retains
(IMAP client, IDLE, providers, OAuth, parser primitives) were ported
to src/accountpilot/plugins/mail/ in Tasks 5-9. Everything else was
out of scope for v1 (database/Xapian/tags/events/SMTP/Maildir sync)
and is removed here.

After this commit:
- src/mailpilot/ no longer exists.
- The mailpilot console script is gone (Task 1).
- The mailpilot tests are removed (their successors live under
  tests/accountpilot/plugins/mail/ where applicable).

git grep mailpilot returns matches only in docs/ (intentional history).
EOF
)"
```

---

### Task 17: Documentation updates

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `ROADMAP.md`
- Modify: `CHANGELOG.md`

After deletion, the legacy MailPilot README content is misleading. Replace it with the AccountPilot README. Update CLAUDE.md's "What This Repo Is" section to reflect post-SP1 reality. Mark AP-SP1 done in ROADMAP.md.

- [ ] **Step 1: Replace `README.md`**

Replace the entire file with:

```markdown
# AccountPilot

A unified per-machine account sync framework. Pulls email, calendar,
iMessage, Telegram, and WhatsApp data into a local SQLite database
through a plugin architecture.

## Status

- **AP-SP0:** complete — core foundation (schema, Storage façade,
  plugin contract, CLI scaffolding, identity resolution, CAS).
- **AP-SP1:** complete — real mail plugin with IMAP IDLE, single Gmail
  account, password_cmd auth.
- **AP-SP2:** next — iMessage plugin (file-watch on chat.db).
- **AP-SP3:** OAuth, multi-account, polish.

## Quickstart

```bash
pip install -e ".[dev]"

mkdir -p ~/.config/accountpilot ~/runtime/accountpilot
cp config.example.accountpilot.yaml ~/.config/accountpilot/config.yaml
# edit owners + plugins.mail.accounts to taste

accountpilot setup
accountpilot mail backfill 1   # account_id from `accountpilot status`
accountpilot mail daemon       # long-running; or run via launchd
```

## Documentation

- Design: `docs/specs/2026-05-01-storage-rewrite-design.md`
- Roadmap & sub-slice plans: `docs/plans/`
- Project conventions: `CLAUDE.md`

## Architecture invariants

- Plugins never write to the DB or to disk directly. They call the
  `Storage` façade, which is the sole writer.
- Identity is first-class: a unified `people` table with an
  `identifiers` map. Same person across email/phone/iMessage handle
  collapses to one row.
- Schema is one local SQLite file at `~/runtime/accountpilot/accountpilot.db`.
  Attachments live in a content-addressed store on disk.

See `CLAUDE.md` for the full set.
```

- [ ] **Step 2: Update `CLAUDE.md`**

In `CLAUDE.md`, find the "What This Repo Is" section and update:

Replace:
> It is the renamed and restructured successor to MailPilot. As of 2026-05-01 the repo has been renamed (GitHub + local folder + remote URL), but **no internal code changes have happened yet** — `src/mailpilot/` still contains the old MailPilot code, `pyproject.toml` still names the project `mailpilot`. The internal rename to `accountpilot` is AP-SP1 work.

With:
> Successor to MailPilot. AP-SP0 (core foundation) and AP-SP1 (real mail
> plugin) are complete. `src/mailpilot/` was deleted in AP-SP1 (commit ahead);
> all source lives under `src/accountpilot/`. The Phase 1 work is now AP-SP2
> (iMessage plugin) and AP-SP3 (OAuth + multi-account + polish).

In the "Sub-Slice Ordering" section, mark SP0 and SP1 as **DONE** (✓) and SP2/SP3 as remaining.

- [ ] **Step 3: Update `ROADMAP.md`**

Find the AP-SP1 section and mark its tasks complete. Update "Current Status" to reflect post-SP1 reality (mail working end-to-end, mailpilot deleted).

- [ ] **Step 4: Update `CHANGELOG.md`**

Add a new entry at the top:

```markdown
## [Unreleased] — 2026-05-XX (AP-SP1)

### Added
- Mail plugin under `accountpilot.plugins.mail`: IMAP client, IDLE
  listener, Gmail/Outlook providers, OAuth helper, RFC822 → EmailMessage
  parser, sync orchestrator, MailPlugin lifecycle, `mail backfill/sync/daemon`
  CLI subcommands.
- `Secrets.resolve` recognizes `password_cmd:<shell cmd>` URIs
  (1Password CLI integration via `op read ...` shell wrapper).
- `Storage.latest_imap_uid(account_id, mailbox)` for sync watermarking.
- `MailPluginConfig` / `MailAccountConfig` typed config models for
  the `plugins.mail` block of `config.yaml`.
- Plugin entry-point discovery: root CLI registers plugin Click groups
  via `accountpilot.plugins` entry points instead of hard imports.
- `~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist`
  for AE deployment.

### Changed
- `pyproject.toml` project name flipped from `mailpilot` to `accountpilot`.
  The `mailpilot` console script is removed.
- `Storage.upsert_owner` now auto-merges cross-person identifier
  collisions (per AP-SP0 final review).

### Removed
- `src/mailpilot/` package (entirely).
- `tests/test_*.py` for mailpilot-specific features (composer, smtp,
  search/Xapian, tags, threading, events, database, daemon, cli, api,
  config, sync — replacements live under `tests/accountpilot/`).
- `mailpilot` console script.
```

- [ ] **Step 5: Verify and commit**

```bash
pytest tests/accountpilot -q   # final sanity
ruff check src/accountpilot tests/accountpilot
mypy src/accountpilot

git add README.md CLAUDE.md ROADMAP.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs: AP-SP1 status — mail plugin complete; mailpilot deleted

Replace the legacy MailPilot README with an AccountPilot one. Update
CLAUDE.md to reflect post-SP1 reality (mailpilot is gone). Mark
AP-SP1 done in ROADMAP.md. Add CHANGELOG entry summarizing the slice.
EOF
)"
```

---

### Task 18: Hardware acceptance

**Files:** none modified — this is a manual verification checklist.

The seven scenarios from spec §7.2 must all pass on AE's actual machine before AP-SP1 is closed out. The user runs these; the agent does NOT automate them (they touch real Gmail credentials, real network, real launchd state, real `~/.config/`).

The agent's role for this task is to:
1. Restate the scenarios.
2. Wait for the user to run them.
3. Capture results into a status comment in the plan file or CHANGELOG.

- [ ] **Step 1: Restate the seven scenarios**

```text
AP-SP1 acceptance — run on AE:

1. New email at ardaeren13@gmail.com → row in messages + email_details
   within ~5s of IDLE notification.

   How: have someone send a test email; run `accountpilot mail daemon`
   in one terminal; in another, `accountpilot search "<phrase from email>"`
   should return it immediately.

2. Attachment-bearing email → file in CAS; attachments row present;
   content_hash matches file.

   How: send yourself an attachment-bearing email; check
   `~/runtime/accountpilot/attachments/<hash[:2]>/<hash[2:4]>/<hash>.bin`
   exists and `sqlite3 ~/runtime/accountpilot/accountpilot.db
   "SELECT content_hash, cas_path FROM attachments"`.

3. Sender resolves to a people row (created if new, reused if seen
   before).

   How: `accountpilot people list` after sync. Each unique sender
   shows up exactly once.

4. accountpilot search "<phrase>" returns the email at top.

   Already covered in #1.

5. Daemon survives 24h continuous run; reconnects after a deliberate
   network blip; no duplicate rows on reconnect.

   How: run `accountpilot mail daemon` (or via launchd plist from
   Task 15), toggle wifi off/on once, leave running 24h. Check
   `accountpilot status` after — last_sync_at recent, last_error empty
   or transient. `SELECT COUNT(*), COUNT(DISTINCT external_id) FROM
   messages` — both counts should match (no dupes).

6. src/mailpilot/ no longer exists; git grep mailpilot returns only
   CHANGELOG and migration-note refs.

   How: `ls src/mailpilot 2>&1` shows "No such file"; `git grep
   mailpilot src/ tests/ pyproject.toml` returns zero results outside
   docs/.

7. (implicit) `accountpilot setup` is idempotent against a real
   `~/.config/accountpilot/config.yaml` with one Gmail account.

   How: copy config.example, edit, run setup twice. Second run's
   accounts table has the same row count as after the first.
```

- [ ] **Step 2: User runs scenarios; reports results**

The agent waits for human input. Once the user reports pass/fail, the agent updates `CHANGELOG.md` with the test date and any deferred issues.

- [ ] **Step 3: Tag the slice complete**

If all 7 scenarios pass:

```bash
git tag -a ap-sp1-complete -m "$(cat <<'EOF'
AP-SP1 acceptance passed on AE.

7/7 hardware scenarios verified per spec §7.2:
1. New email → row in messages within ~5s of IDLE.
2. Attachment-bearing email → CAS file + attachments row.
3. Sender resolves to people row.
4. Search returns email at top.
5. Daemon 24h soak; network blip recovery; no dupes.
6. src/mailpilot/ deleted; git grep clean.
7. setup idempotent against real config.yaml.

Next slice: AP-SP2 (iMessage plugin).
EOF
)"
```

If any scenario fails, do NOT tag — open a follow-up task in this plan and fix.

- [ ] **Step 4: Decide next slice**

After AP-SP1 acceptance, the next plan is `2026-05-XX-accountpilot-ap-sp2.md` (iMessage plugin). Out of scope for this slice.

---

## Summary of commits

| # | Subject |
|---|---------|
| 1  | chore: rename project to accountpilot; drop mailpilot script + package |
| 2  | feat(core/auth): real Secrets.resolve with password_cmd: scheme |
| 3  | fix(core/storage): upsert_owner auto-merges cross-person collisions |
| 4  | feat(core/storage): add latest_imap_uid helper |
| 5  | feat(plugins/mail): port providers package |
| 6  | feat(plugins/mail): port IMAP client |
| 7  | feat(plugins/mail): port IMAP IDLE listener |
| 8  | feat(plugins/mail): port OAuth helper |
| 9  | feat(plugins/mail): typed RFC822 parser |
| 10 | feat(plugins/mail): config models for mail plugin |
| 11 | feat(plugins/mail): sync orchestrator |
| 12 | feat(plugins/mail): MailPlugin with 5 lifecycle hooks |
| 13 | feat(plugins/mail/cli): add accountpilot mail {backfill,sync,daemon} |
| 14 | feat(cli): register plugin subgroups via entry-point discovery |
| 15 | feat(ae/launchd): com.accountpilot.mail.daemon job (in infra repo) |
| 16 | chore: delete src/mailpilot/ and obsolete tests |
| 17 | docs: AP-SP1 status — mail plugin complete; mailpilot deleted |
| 18 | (acceptance — no commit; produces tag `ap-sp1-complete`) |
