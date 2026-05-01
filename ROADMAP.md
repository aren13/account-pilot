# AccountPilot Roadmap

> Forward-looking plan for AccountPilot. Architecture is in `ARCHITECTURE.md`; the upstream system spec is `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md`.
>
> **Last updated:** 2026-05-01

## Overview

AccountPilot is a unified account sync framework — pulls content from external services (email, calendar, iMessage, Telegram, WhatsApp) into a per-machine, per-space knowledge base via a plugin architecture. It is a first-class component of the `infra` fleet (4 machines on Tailscale, distributed Qdrant KB).

Phase 1 delivers the core plus the mail plugin end-to-end. Subsequent phases add calendar, iMessage, Telegram, and WhatsApp.

## Current Status

The repo contains a working IMAP/SMTP/Xapian email engine (~3,100 LOC) under `src/mailpilot/`, scheduled to be lifted into `src/accountpilot/plugins/mail/` in AP-SP1. Tooling in place: pytest + pytest-asyncio + pytest-cov, ruff, mypy, pre-commit. No AccountPilot core code exists yet; AP-SP0 is the next sub-slice.

## Phase 1 — Core + Mail Plugin

> Goal: AccountPilot core + mail plugin running on AE for 3 Gmail accounts (`aren`, `fazla`, `cm`), feeding the infra KB pipeline end-to-end.
>
> Broken into 4 sequential, independently shippable sub-slices.

### AP-SP0 — Foundation

> Goal: Build the shared `sidecar-schemas` package that the storage adapter depends on. No AccountPilot code yet.

**Tasks**

- [ ] Build `sidecar-schemas` package at `~/Projects/infra/scripts/sidecar_schemas/` — Pydantic v2 models for all 6 source types per `ARCHITECTURE.md` §8 (documents, emails, messages, photos, voices, notes), plus calendar
- [ ] Refactor existing `infra/scripts/ingest/` to consume `sidecar-schemas` (proves schema parity before AccountPilot depends on it)
- [ ] Write AP-SP1 plan at `~/Projects/infra/specs/plans/2026-05-XX-accountpilot-ap-sp1.md`

**Acceptance**

- `sidecar-schemas` builds and is installable via `uv pip install -e ~/Projects/infra/scripts/sidecar_schemas`
- Existing `scripts/ingest/` test suite passes after refactor
- AP-SP1 plan reviewed and approved

### AP-SP1 — Core + skeleton mail plugin

> Goal: Build `accountpilot.core` and a stub `mail` plugin that emits synthetic events. Prove the contract end-to-end without real IMAP traffic.

**Tasks**

- [ ] Rename `src/mailpilot/` → `src/accountpilot/`; update `pyproject.toml` `name = "accountpilot"`; update CLI entry point
- [ ] Build `accountpilot.core` modules:
  - `core/config.py` — XDG paths, plugin enable list, schema validation
  - `core/events.py` — async event emitter and typed event models
  - `core/router.py` — rule-based space routing with `unclassified` fallback
  - `core/storage.py` — owner-aware adapter; reads `~/spaces/<space>/meta.json` to choose local vs outbound write path
  - `core/auth.py` — `password_cmd` + Keychain shim + OAuth file resolution
  - `core/cli.py` — Click root group with per-plugin subcommand registration
  - `core/plugin.py` — `AccountPilotPlugin` base class with 5 lifecycle hooks
- [ ] Move existing IMAP/SMTP/Xapian/threading/tags code under `src/accountpilot/plugins/mail/`, adapted to emit `mail.new` events instead of writing to `mail.db`
- [ ] Stub `mail.sync_once()` to emit one synthetic `mail.new` event for path validation
- [ ] Log finding for `ARCHITECTURE.md` §6.13 (owner-aware storage) in `~/Projects/infra/specs/DELTAS.md`

**Acceptance**

- `accountpilot mail sync` emits a synthetic event → storage adapter writes payload + sidecar to `~/outbound/aren/data/emails/`
- AE has read access to `~/spaces/aren/meta.json` (synced from Lola or stubbed for SP1) so the owner-aware adapter resolves "AE is non-owner of `aren`"
- AE's `com.aren.outbound-watcher` ships the file to Lola
- Lola's `com.aren.inbox-ingest` + `com.aren.embed` pick it up
- `kb query "synthetic test message"` from AE returns the synthetic message
- All migrated pytest tests pass under the new package name

### AP-SP2 — Real mail plugin (one account)

> Goal: Wire IMAP IDLE into the plugin so real Gmail messages flow into the KB. Single account: personal Gmail → `aren` space.

**Tasks**

- [ ] `mail.sync_once()` calls real IMAP fetch; emits one `mail.new` event per message
- [ ] `mail.daemon()` wraps IMAP IDLE in the plugin lifecycle
- [ ] Per-account config gains `space` field
- [ ] Auth: `password_cmd` + 1Password CLI (`op read op://Personal/gmail-personal/password`)
- [ ] Email body and attachments split: body as one file, each attachment as its own file with appropriate sidecar; attachments link to body via sidecar `parent_id`
- [ ] Xapian index moves to `~/runtime/accountpilot/xapian/`
- [ ] launchd job `com.accountpilot.mail.daemon` deployed via `~/Projects/infra/configs/machines/ae/launchd/`

**Acceptance** (7-scenario hardware test)

1. New email arrives → `~/outbound/aren/data/emails/{YYYYMMDD}_{hash6}.eml` within IDLE notification window (~seconds)
2. Sidecar JSON conforms to `sidecar-schemas` email model
3. File ships to Lola via outbound-watcher
4. Lola's pipeline embeds it into `qdrant-aren`
5. `kb query "<phrase from email body>"` from AE returns the email at top
6. Attachment-bearing email → body + each attachment as separate KB entries, all linked via sidecar `parent_id`
7. Daemon survives 24h continuous run; IDLE reconnects after network blip; no duplicate sidecars (dedup via checksum)

### AP-SP3 — Migration + multi-account

> Goal: Migrate existing MailPilot data, add OAuth, add `fazla` and `cm` accounts. After this, mail is feature-complete.

**Tasks**

- [ ] `accountpilot migrate-from-mailpilot` command:
  1. Detect `~/.mailpilot/`
  2. Convert config to new schema (prompt for `space` per account)
  3. Replay all messages in `mail.db` through the storage adapter (dedup via checksum makes re-runs idempotent)
  4. Verify `count(mail.db) == count(written sidecars)`
  5. User confirms; `~/.mailpilot/` is then safe to delete
- [ ] Flags: `--dry-run` (emit but don't ship), `--limit N` (staged migration), `--resume-from <checksum>` (restartable partial migrations)
- [ ] OAuth flow for Gmail (Google API client; refresh token at `~/runtime/accountpilot/secrets/oauth/google/<account>.json`)
- [ ] Add `fazla` account → `fazla` space (writes to `~/outbound/fazla/`)
- [ ] Add `cm` account → `cm` space (writes to `~/outbound/cm/`)
- [ ] Multi-space isolation test: 3 simultaneous IDLE sessions, all queryable from AE via federated `kb`

**Acceptance**

- Migration on AE completes without data loss; mail.db count matches sidecar count
- OAuth flow works for fresh account add (no app-password fallback needed)
- 3-account, 3-space concurrent operation; isolation verified — a `fazla` email never lands in `aren`, etc.
- Old `mailpilot` CLI fully removed (no shim, no compat layer)

### Phase 1 Deliverables

- `accountpilot` package replaces `mailpilot` (old package marked deprecated)
- CLI: `accountpilot status | sync | daemon | mail [sync|search|send|tag] | migrate-from-mailpilot`
- Mail plugin deployed on AE for 3 accounts (personal, fazla, cm), all flowing into the infra KB pipeline
- `sidecar-schemas` consumed by both AccountPilot and `infra/scripts/ingest/`
- Acceptance test suites for all 4 sub-slices

## Phase 2 — Calendar Plugin

> Goal: Add calendar plugin for Google + Outlook. Apple Calendar deferred to Phase 3.
>
> Why second: Calendar shares OAuth scopes with Gmail/Outlook; one consent covers both. Marginal cost given AP-SP3 already implements OAuth.

**Tasks**

- [ ] Add calendar source type to `sidecar-schemas` per `ACCOUNT_PILOT_SPEC.md` §7.2
- [ ] Build `accountpilot.plugins.calendar`
- [ ] Google Calendar backend (Google Calendar API; reuses Gmail OAuth client)
- [ ] Outlook Calendar backend (Microsoft Graph; reuses Outlook OAuth client)
- [ ] Sync modes: backfill (default 2y past → 2y future), live sync (Google push or 5-min poll, Graph change notifications), incremental via sync tokens / `deltaLink`
- [ ] Versioning: modified events trigger update flow per infra `ARCHITECTURE.md` §10

**Acceptance**

- Google Calendar event created/modified/deleted on phone → reflected in `kb query` within 5 minutes
- Working calendar plugin on AE for personal + Fazla Google calendars + CM Outlook
- Calendar source type formally added to infra `ARCHITECTURE.md` §6.2

## Phase 3 — iMessage / Telegram / Apple Calendar

> Goal: Cover the remaining message and scheduling surfaces.

**Tasks**

- [ ] Apple Calendar via EventKit (PyObjC), CalDAV fallback
- [ ] iMessage plugin: `~/Library/Messages/chat.db` reader (Full Disk Access required); fsevents watcher; ROWID cursor
- [ ] Telegram plugin: Telethon; per-chat opt-in; one session-holder machine (AE)

**Acceptance**

- All three plugins deployed per `ACCOUNT_PILOT_SPEC.md` §16 deployment matrix
- Plugin contract validated across event-driven, OAuth-polled, and direct-DB plugin shapes

## Phase 4 — WhatsApp + Long-Tail Sources

> Goal: WhatsApp (manual export only in v1) and any sources that emerge during agent activation.

**Tasks**

- [ ] WhatsApp plugin: `chat.txt` parser + zip handler + space routing via `--space` flag or filename inference
- [ ] (Deferred, conditional) WhatsApp live sync if a sustainable approach emerges
- [ ] (Future, conditional) Slack, Teams, Notion, Obsidian — only where infra-native connectors don't already cover them

**Acceptance**

- WhatsApp manual import working end-to-end on AE
- Decision logged on whether AccountPilot or infra-native connectors handle Slack / Teams / etc.

## See Also

- `ARCHITECTURE.md` — implementation architecture for this repo
- `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md` — canonical AccountPilot system spec
- `~/Projects/infra/specs/ARCHITECTURE.md` — fleet-wide KB architecture
- `~/Projects/infra/ROADMAP.md` — fleet-wide roadmap (AccountPilot is its Phase 1)
- `~/Projects/infra/specs/DELTAS.md` — pending spec amendments
