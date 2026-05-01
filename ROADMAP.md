# AccountPilot Roadmap

> Unified account sync framework. Pulls content from external services (email, calendar, iMessage, Telegram, WhatsApp) into a per-machine knowledge base via a plugin architecture.
>
> **Created:** 2026-05-01
> **Status:** Pre-AP-SP0 — repo just renamed from `mail-pilot`, no AccountPilot code yet
> **Upstream spec:** `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md` (v1.0, 2026-04-14)

---

## What This Repo Is

AccountPilot is the renamed and restructured successor to MailPilot. MailPilot was a single-purpose IMAP/SMTP/Xapian email engine. AccountPilot keeps that engine intact as the `mail` plugin and adds a small async core (config, event bus, space router, storage adapter, CLI shell) plus additional plugins for calendar, iMessage, Telegram, WhatsApp.

The repo lives standalone (`github.com/aren13/account-pilot`) but is a **first-class component of Aren's `infra` fleet** — its design and deployment are coordinated with `~/Projects/infra/` (4-machine fleet, Tailscale-networked, distributed knowledge base on Qdrant).

## Relationship to MailPilot

This **is** MailPilot. The git history is preserved. The package, CLI, config path, and storage all change in AP-SP1.

| | MailPilot (old) | AccountPilot (new) |
|---|---|---|
| Repo | `aren13/mail-pilot` | `aren13/account-pilot` |
| Package | `mailpilot` | `accountpilot.core` + `accountpilot.plugins.mail` |
| CLI | `mailpilot` | `accountpilot` (`accountpilot mail …` for mail subcommands) |
| Config | `~/.mailpilot/config.yaml` | `~/.config/accountpilot/config.yaml` (XDG-compliant) |
| Mail storage | `~/.mailpilot/mail.db` | `~/spaces/<space>/data/emails/` (or `~/outbound/<space>/data/emails/` on hosts that don't own the space — see AP-SP0) |
| Xapian index | `~/.mailpilot/xapian/` | `~/runtime/accountpilot/xapian/` |
| Operational state | `~/.mailpilot/mail.db` | `~/runtime/accountpilot/state.db` |

**No backward compatibility.** A one-shot `accountpilot migrate-from-mailpilot` command (AP-SP3) handles transition; the `mailpilot` CLI is gone after the rename PR lands.

## Current Status (2026-05-01)

**What exists:**
- ~3,100 LOC of MailPilot code under `src/mailpilot/` (still named `mailpilot` — rename is AP-SP1)
- Working IMAP IDLE, SMTP, Xapian search, JWZ threading, Click CLI, async event emitter, Pydantic models, SQLite metadata store, Gmail + Outlook provider modules, auto-tag rules
- Test suite (pytest + pytest-asyncio + pytest-cov), ruff, mypy, pre-commit
- `pyproject.toml` still names the project `mailpilot`
- Repo renamed on GitHub + local folder moved, but **no internal code changes yet**

**What does not exist:**
- AccountPilot core (config loader for new schema, space router, storage adapter, owner-aware write routing)
- Plugin contract base class (`AccountPilotPlugin`)
- Sidecar generation (depends on `sidecar-schemas` package — does not exist yet, blocker tracked in `infra/ROADMAP.md` Phase 1)
- Calendar plugin
- iMessage plugin
- Telegram plugin
- WhatsApp plugin
- Migration script

## Architecture (Target)

```
┌───────────────────────────────────────────────────────────────┐
│                     accountpilot.core                         │
│   config loader · event bus · space router                    │
│   auth / keychain · storage adapter · CLI framework           │
└─────┬────────┬────────┬────────┬────────┬────────────────────┘
      │        │        │        │        │
      ▼        ▼        ▼        ▼        ▼
  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
  │ mail │ │ cal  │ │imsg  │ │telgm │ │whats │
  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘
     └────────┴────────┴────────┴────────┘
                       │
                       ▼
        ┌──────────────────────────────────────┐
        │  storage adapter → owner-aware       │
        │  • space owner: ~/spaces/<space>/…   │
        │  • non-owner:   ~/outbound/<space>/… │
        └──────────────────────────────────────┘
```

Plugins emit typed events (`mail.new`, `calendar.event`, `message.new`). Core's storage adapter consumes them, applies space routing, generates sidecars, writes to disk. **Plugins never touch disk or network for storage.**

For the full architecture, see `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md`.

---

## Phase 1 — AccountPilot Core + Mail Plugin Slice v0.1

> **Goal:** Replace MailPilot with AccountPilot core + mail plugin, end-to-end working on AE for a single Gmail account, writing to the infra KB pipeline.
>
> **Prerequisite:** none (other than infra fleet's `ARCHITECTURE.md` v1.5 and L-SP3 cutover, both done)
> **Blocks:** every other plugin (Phase 2 + Phase 1.5 from infra roadmap)

The slice is broken into 4 sub-slices (AP-SP0 through AP-SP3), each independently shippable + acceptance-testable. Pattern follows the F-SP / L-SP cadence proven in the infra repo.

### AP-SP0 — Foundation (no behavior change)

> **Goal:** Lock decisions and build the shared `sidecar-schemas` package that the storage adapter will depend on. No AccountPilot code written yet; MailPilot still works as-is.

**Tasks:**
- [ ] Decide: in-place rename of `src/mailpilot/` → `src/accountpilot/` in AP-SP1, or keep `mailpilot/` as a deprecated shim during the migration window? **(see Open Questions Q1)**
- [ ] Decide: amend `infra/specs/ARCHITECTURE.md` to add §6.13 "Owner-aware Outbound Storage" before AP-SP1, or document via `DELTAS.md` and amend after slice ships? **(see Open Questions Q2)**
- [ ] Build `sidecar-schemas` Python package (Pydantic v2 models for all 6 source types per `ARCHITECTURE.md` §8: documents, emails, messages, photos, voices, notes — and calendar to come). Lives in `~/Projects/infra/scripts/sidecar_schemas/` so existing `scripts/ingest/` and `scripts/embed/` can adopt it too.
- [ ] Refactor existing `scripts/ingest/` to consume `sidecar-schemas` (proves schema parity before AccountPilot depends on it).
- [ ] Write plan: `infra/specs/plans/2026-05-XX-accountpilot-ap-sp0.md` (per `infra/CLAUDE.md` plan convention).

**Acceptance:**
- `sidecar-schemas` package builds and is installable via `uv pip install -e ~/Projects/infra/scripts/sidecar_schemas`
- `scripts/ingest/` test suite still passes after refactor
- AP-SP1 plan reviewed and approved

### AP-SP1 — Core + skeleton mail plugin

> **Goal:** Build `accountpilot.core` (config, event bus, router, storage adapter, CLI shell) and wrap it in a stub `mail` plugin that emits synthetic events. Prove the contract end-to-end without touching IMAP yet.

**Tasks:**
- [ ] Rename `src/mailpilot/` → `src/accountpilot/`; rename `pyproject.toml` `name = "accountpilot"`; rename CLI entry point.
- [ ] Extract `accountpilot.core` modules:
  - `core/config.py` (XDG paths, plugin enable list, schema validation)
  - `core/events.py` (lift from MailPilot's `events/emitter.py` + `events/types.py`)
  - `core/router.py` (space routing rules, fallback to `unclassified`)
  - `core/storage.py` (owner-aware adapter; reads `~/spaces/<space>/meta.json` to decide local vs outbound write path)
  - `core/auth.py` (lift MailPilot's password_cmd + add Keychain shim + OAuth file resolution)
  - `core/cli.py` (Click group; per-plugin subcommand registration)
  - `core/plugin.py` (`AccountPilotPlugin` base class with 5 lifecycle hooks)
- [ ] Move existing IMAP/SMTP/Xapian/tags code under `src/accountpilot/plugins/mail/` (still functional, but adapted to plugin contract — emits `mail.new` events instead of writing to `mail.db`).
- [ ] Stub `sync_once()` on the mail plugin: emit one synthetic `mail.new` event for testing the full path.
- [ ] Storage adapter writes sidecar + payload to either `~/spaces/aren/data/emails/` (when AE owns `aren`, which it doesn't post-L-SP3) or `~/outbound/aren/data/emails/` (when AE is non-owner).

**Acceptance:**
- `accountpilot mail sync` emits a synthetic event → storage adapter writes JSON + sidecar to `~/outbound/aren/data/emails/`
- AE's existing `com.aren.outbound-watcher` ships the file to Lola
- Lola's `com.aren.inbox-ingest` + `com.aren.embed` pick it up
- `kb query "synthetic test message"` from AE returns the synthetic message
- All MailPilot pytest tests pass under the new package name (or are explicitly migrated/dropped)

### AP-SP2 — Real mail plugin (one account)

> **Goal:** Wire MailPilot's IMAP IDLE / sync code into the plugin so real Gmail messages flow into the KB. Single account: Aren's personal Gmail → `aren` space.

**Tasks:**
- [ ] Mail plugin `sync_once()` calls existing IMAP fetch logic, emits one `mail.new` event per message.
- [ ] Mail plugin `daemon()` wraps IMAP IDLE in the plugin lifecycle.
- [ ] Per-account config gains `space` field (single account: personal Gmail → `aren`).
- [ ] Auth: `password_cmd` + 1Password CLI (`op read op://Personal/gmail-personal/password`). OAuth deferred to AP-SP3.
- [ ] Email body + attachments split: body as one file in `data/emails/`, each attachment as its own file with appropriate sidecar (per `ACCOUNT_PILOT_SPEC.md` §6).
- [ ] Xapian index moves to `~/runtime/accountpilot/xapian/`.
- [ ] launchd plist: `com.accountpilot.daemon` for IDLE, deployed via `infra/configs/machines/launchd/`.

**Acceptance (7-scenario hardware acceptance, matching infra slice pattern):**
1. New email arrives → ends up in `~/outbound/aren/data/emails/{YYYYMMDD}_{hash6}.eml` within IDLE notification window (~seconds)
2. Sidecar JSON conforms to `sidecar-schemas` email model
3. File ships to Lola via outbound-watcher
4. Lola's pipeline embeds it into `qdrant-aren`
5. `kb query "<phrase from email body>"` from AE returns the email at top
6. Attachment-bearing email → body + each attachment as separate KB entries, all linked via sidecar `parent_id`
7. Daemon survives 24h continuous run; IDLE reconnects after network blip; no duplicate sidecars (dedup via checksum)

### AP-SP3 — Migration + multi-account hardening

> **Goal:** Migrate existing MailPilot data, add OAuth path, add Fazla + CM accounts. After this, AccountPilot is feature-complete for mail; calendar plugin work begins.

**Tasks:**
- [ ] `accountpilot migrate-from-mailpilot` command:
  1. Detect `~/.mailpilot/`
  2. Convert config to new schema (prompt for `space` per account)
  3. Replay all messages in `mail.db` through storage adapter (dedup via checksum makes re-runs safe)
  4. Verify: count(mail.db) == count(written sidecars)
  5. User confirms; safe to delete `~/.mailpilot/`
- [ ] OAuth flow for Gmail (Google API client; refresh token persisted at `~/runtime/accountpilot/secrets/oauth/google/<account>.json`).
- [ ] Add `fazla` account → `fazla` space (writes to `~/outbound/fazla/`).
- [ ] Add `cm` account → `cm` space (writes to `~/outbound/cm/`).
- [ ] Multi-space routing test: 3 simultaneous IDLE sessions, 3 spaces, all queryable from AE via federated `kb`.

**Acceptance:**
- Migration on AE completes without data loss; mail.db count matches sidecar count
- OAuth flow works for fresh account add (no app-password fallback needed)
- 3-account, 3-space concurrent operation; isolation verified (a `fazla` email never lands in `aren` space, etc.)
- Old `mailpilot` CLI fully removed (no shim, no compat layer)

### Phase 1 Deliverables

- `accountpilot` package on PyPI (replaces `mailpilot`; old package marked deprecated)
- Working CLI: `accountpilot status | sync | daemon | mail [sync|search|send|tag] | migrate-from-mailpilot`
- Mail plugin deployed on AE for 3 accounts (personal, fazla, cm) — all flowing into infra KB pipeline
- `sidecar-schemas` package consumed by both AccountPilot and infra `scripts/ingest/`
- Acceptance test suites for all 4 sub-slices

---

## Phase 2 — Calendar Plugin

> **Goal:** Add calendar plugin (Google + Outlook). Apple Calendar deferred to Phase 3.
> **Prerequisite:** Phase 1 complete (plugin contract proven on mail)
> **Blocks:** infra Phase 4 agent capabilities that need scheduling context

**Why second:** Calendar shares OAuth scopes with Gmail/Outlook (one consent covers both). Marginal cost given AP-SP3 already does OAuth for mail.

### Tasks
- [ ] Calendar source type added to `sidecar-schemas` (per `ACCOUNT_PILOT_SPEC.md` §7.2)
- [ ] `accountpilot.plugins.calendar` package
- [ ] Google Calendar backend (Google Calendar API; reuses Gmail OAuth client)
- [ ] Outlook Calendar backend (Microsoft Graph; reuses Outlook OAuth client)
- [ ] Sync modes: backfill (default 2y past → 2y future), live sync (Google push or 5-min poll, Graph change notifications), incremental (sync tokens / deltaLink)
- [ ] Versioning: modified events trigger update flow per infra `ARCHITECTURE.md` §10
- [ ] Acceptance: Google Calendar event created/modified/deleted on phone → reflected in `kb query` within 5 min

### Deliverables
- Working calendar plugin on AE for personal + Fazla Google calendars + CM Outlook
- Calendar source type formally added to infra `ARCHITECTURE.md` §6.2 (will require lifting infra spec freeze)

---

## Phase 3 — iMessage / Telegram / Apple Calendar (formerly infra Phase 1.5)

> **Goal:** Cover the remaining message and scheduling surfaces.
> **Prerequisite:** Phase 2 complete (plugin contract validated across event-driven, polled, and OAuth-driven shapes)

### Tasks
- [ ] Apple Calendar via EventKit (PyObjC), CalDAV fallback
- [ ] iMessage plugin (`~/Library/Messages/chat.db` reader; Full Disk Access required; fsevents watcher; ROWID cursor)
- [ ] Telegram plugin (Telethon; per-chat opt-in; one session-holder machine — likely AE)

### Deliverables
- All three plugins deployed per `ACCOUNT_PILOT_SPEC.md` §16 deployment matrix
- Plugin contract validated across all three plugin shapes

---

## Phase 4 — WhatsApp + Long-Tail Sources

> **Goal:** Cover WhatsApp (manual export only in v1) and any sources that emerge during agent activation.
> **Prerequisite:** Phase 3 complete

### Tasks
- [ ] WhatsApp plugin: `chat.txt` parser + zip handler + space routing via `--space` flag or filename inference
- [ ] (Optional, deferred to evaluation) WhatsApp live sync if a sustainable approach emerges (whatsmeow / Baileys evaluated but ban risk; Business Cloud has no historical access)
- [ ] (Future) Slack, Teams, Notion, Obsidian — only if they don't already have native infra connectors that bypass AccountPilot

### Deliverables
- WhatsApp import working end-to-end on AE
- Decision document on whether AccountPilot or infra-native connectors handle Slack/Teams/etc.

---

## Decision Log

| Date | Decision | Context |
|---|---|---|
| 2026-04-14 | MailPilot → AccountPilot rename; scope expanded to unified account sync (mail + calendar + iMessage + Telegram + WhatsApp) | Single auth + storage + routing layer for all external accounts; plugin-based |
| 2026-04-14 | Rename in place; drop MailPilot backcompat | Clean cut; one-shot migration script handles transition |
| 2026-04-14 | Keep Xapian inside mail plugin | Fast keyword search is cheap to retain alongside Qdrant semantic layer |
| 2026-04-14 | Calendar OAuth extends Gmail/Outlook scopes; Apple Calendar via EventKit (PyObjC) primary / CalDAV fallback | One consent per Google/Microsoft account covers both mail + calendar |
| 2026-04-14 | iMessage plugin reads `~/Library/Messages/chat.db` directly; no public API exists | Industry-standard approach; Full Disk Access required |
| 2026-04-14 | WhatsApp: manual export backfill only in Phase 1; live sync deferred | Skips ban risk of whatsmeow/Baileys; revisitable later |
| 2026-04-14 | AccountPilot plugins write snapshots only; never touch `~/Documents/spaces/<space>/` live tree | Live tracking is for user-worked files; external sources are always archival |
| 2026-04-14 | Plugins emit events; core's storage adapter is sole writer | Decouples plugins from disk layout; enables consistent dedup, sidecars, versioning |
| 2026-04-14 | XDG-compliant config path: `~/.config/accountpilot/config.yaml` | Cleaner than `~/.mailpilot/`; matches Linux/macOS convention |
| 2026-04-22 | Phase 1 scope cut to core + mail + calendar only; iMessage/Telegram/WhatsApp moved to later phases | Prove plugin contract on 2 plugins (event-driven + OAuth-polled) before multiplying. Mail is highest-value, calendar shares OAuth |
| 2026-05-01 | GitHub repo renamed `aren13/mail-pilot` → `aren13/account-pilot`; local folder `~/Code/mail-pilot` → `~/Code/account-pilot` | Rename completed; internal code rename is AP-SP1 work |
| 2026-05-01 | Slice broken into 4 sub-slices (AP-SP0..AP-SP3) following infra F-SP / L-SP cadence | Each sub-slice independently shippable + hardware-acceptance-tested |

---

## Open Questions

**Q1 — `mailpilot` package shim during AP-SP1?**
In-place rename `src/mailpilot/` → `src/accountpilot/` is clean but instantly breaks any external code importing `mailpilot`. Realistically nothing outside this repo imports it (alpha, never published as load-bearing dep). Recommendation: hard cut in AP-SP1, no shim. **Confirm before AP-SP1.**

**Q2 — When to amend `ARCHITECTURE.md` for owner-aware storage?**
Storage adapter must distinguish "this host owns the space → write to `~/spaces/<space>/`" vs "this host doesn't own it → write to `~/outbound/<space>/`". The infra `ARCHITECTURE.md` v1.5 doesn't formally name this pattern (§6.12 covers cross-host transfer mechanism but not the adapter-side decision logic).
- Option A: amend `ARCHITECTURE.md` §6.13 before writing the adapter (clean, but requires lifting spec freeze)
- Option B: implement adapter, log finding to `infra/specs/DELTAS.md`, amend post-acceptance
- Recommendation: Option B (matches the infra workflow that's been working). Decide before AP-SP1.

**Q3 — Slice v0.1 host scope: AE-only or AE + Lola simultaneously?**
`ACCOUNT_PILOT_SPEC.md` §6 says "separate OAuth per machine — Lola can't piggyback on AE's auth." But running IMAP IDLE on the same Gmail account from two machines is something Gmail tolerates poorly. Recommendation: AE-only for AP-SP1/SP2; revisit Lola in AP-SP3 with explicit per-machine OAuth tokens. **Confirm before AP-SP1.**

**Q4 — `sidecar-schemas` package home: subpackage in infra, or standalone repo?**
Pros of subpackage in `infra/scripts/sidecar_schemas/`: easy sync via existing infra mechanisms; tight coupling with `ARCHITECTURE.md`; one source of truth. Cons: AccountPilot becomes coupled to infra repo for installation. Pros of standalone: AccountPilot stays installable from PyPI alone. Recommendation: subpackage in infra for now (faster to iterate); promote to standalone if/when AccountPilot is open-sourced. **Decide in AP-SP0.**

**Q5 — Auth for AP-SP2: `password_cmd` + 1Password vs OAuth from day one?**
`password_cmd` works today and matches MailPilot pattern. OAuth is the long-term right answer (Gmail will deprecate app-password auth eventually, and OAuth is required for Calendar). Recommendation: ship AP-SP2 with `password_cmd`, add OAuth in AP-SP3 — keeps slice scope tight. **Confirm before AP-SP2.**

**Q6 — Per-machine deployment for mail plugin: how does Lola's personal-Gmail account avoid conflicting with AE's?**
Per `ACCOUNT_PILOT_SPEC.md` §6: "Lola: personal Gmail only (piggyback on AE's auth is not allowed — separate OAuth per machine)." But two IMAP IDLE sessions on the same Gmail account = Gmail closes one. Options:
- A) Only AE runs the personal-Gmail mail plugin; Lola gets emails via the KB that AE produces
- B) Use Gmail's separate device tokens; both run, both IDLE
- C) Active-passive: AE has IDLE, Lola does periodic sync as fallback if AE is offline
Recommendation: Option A is simplest and matches the post-L-SP3 reality (AE writes, Lola hosts). **Decide in AP-SP3 or defer to Phase 2.**

**Q7 — Migration safety: dry-run mode for `migrate-from-mailpilot`?**
A long-running re-embed of every historical email is expensive (Lola Qdrant load, network bandwidth). Recommendation: `--dry-run` flag that emits but doesn't ship; `--limit N` flag for staged migration. **Decide in AP-SP3.**

---

## See Also

- `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md` — full architecture spec (this roadmap implements it)
- `~/Projects/infra/specs/ARCHITECTURE.md` — KB storage, sidecars, space isolation, owner-aware patterns
- `~/Projects/infra/ROADMAP.md` — fleet-wide roadmap; AccountPilot is Phase 1 of that
- `~/Projects/infra/specs/DELTAS.md` — design freeze notes; AccountPilot scope reshuffle (2026-04-22)
- `~/Projects/infra/specs/CLAUDE_CODE_SPEC.md` — secrets handling pattern reused here
- Upstream repo: `github.com/aren13/account-pilot`
