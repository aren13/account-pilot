# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Repo Is

`account-pilot` is a unified account sync framework — pulls content from external services (email, calendar, iMessage, Telegram, WhatsApp) into a per-machine knowledge base via a plugin architecture.

It is the renamed and restructured successor to MailPilot. As of 2026-05-01 the repo has been renamed (GitHub + local folder + remote URL), but **no internal code changes have happened yet** — `src/mailpilot/` still contains the old MailPilot code, `pyproject.toml` still names the project `mailpilot`. The internal rename to `accountpilot` is AP-SP1 work.

Treat `ROADMAP.md` as the source of truth for what exists, what is planned, and the open questions that gate each sub-slice.

## Relationship to the `infra` Fleet

AccountPilot is a first-class component of Aren's `infra` repo at `~/Projects/infra/`. The infra repo holds the architecture spec (`specs/ACCOUNT_PILOT_SPEC.md`), the fleet-wide roadmap, and the deployment infrastructure (launchd, sync, secrets bootstrap). Read these when context is missing:

- `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md` — full architecture (plugin contract, storage, auth, per-machine deployment matrix)
- `~/Projects/infra/specs/ARCHITECTURE.md` — KB storage, sidecar schemas (§8), space isolation, file naming (§7), cross-host transfer (§6.12)
- `~/Projects/infra/ROADMAP.md` — fleet-wide phases; AccountPilot is the keystone of infra's Phase 1
- `~/Projects/infra/specs/DELTAS.md` — design-freeze notes; AccountPilot scope reshuffle (2026-04-22)
- `~/Projects/infra/CLAUDE.md` — fleet topology, isolation invariants, phase ordering rules

## Fleet Topology (Why Multi-Machine Matters)

Four machines on Tailscale:

- **AE** (MBP M4 Max) — admin/owner, runs AccountPilot for all 3 spaces (`aren`, `fazla`, `cm`)
- **Lola** — hosts the `aren` space (Qdrant + ingest + embed); AE ships data here via `~/outbound/aren/`
- **Rakun** — hosts the `fazla` space; AE ships data here via `~/outbound/fazla/`
- **Tita** — hosts the `cm` space; AE ships data here via `~/outbound/cm/`

**Key consequence for AccountPilot:** post L-SP3 (2026-04-26), AE no longer hosts `~/spaces/aren/`. The mail plugin running on AE writes emails to `~/outbound/aren/data/emails/`, not `~/spaces/aren/data/emails/`. The storage adapter must be **owner-aware** — it reads `~/spaces/<space>/meta.json` to decide local vs outbound write path.

## Non-Negotiable Architecture Invariants

These are load-bearing — violating them corrupts the trust model.

- **Plugins never write to disk or network for storage.** Plugins emit events (`mail.new`, `calendar.event`, `message.new`) via the core's event bus. The storage adapter is the sole writer.
- **Plugins never query Qdrant.** Once the storage adapter writes the file + sidecar, AccountPilot's job is done. The KB pipeline (separate, in `infra/scripts/`) handles chunking, embedding, vector storage.
- **Space isolation is absolute.** A `fazla` email must never land in `aren` space, and vice versa. Routing is rule-based; if no rule matches, item goes to `~/inbox/unclassified/` — never auto-guessed.
- **Plugins write snapshots only** (`state: "snapshot"`). AccountPilot never touches the live tree at `~/Documents/spaces/<space>/`.
- **Filename convention:** `{YYYYMMDD}_{hash6}.{ext}` per `ARCHITECTURE.md` §7. The storage adapter enforces this; plugins never pick filenames.
- **Sidecars are self-contained.** Per `ARCHITECTURE.md` invariant: do not infer metadata from folder paths. The sidecar must carry everything needed to understand the file.
- **Secrets never enter the repo.** All credentials live at `~/runtime/accountpilot/secrets/` per machine, bootstrapped from 1Password.
- **No cross-plugin direct imports.** Plugins communicate via the event bus. A plugin importing another plugin is an architecture violation.

## Sub-Slice Ordering

The Phase 1 slice is broken into AP-SP0 → AP-SP3, sequential and gating:

- **AP-SP0** — Foundation. Build `sidecar-schemas` package in infra repo; lock open questions Q1, Q2, Q4.
- **AP-SP1** — Core + skeleton mail plugin. Internal `mailpilot` → `accountpilot` rename happens here. Stub plugin emits synthetic events; storage adapter writes them through to Lola.
- **AP-SP2** — Real mail plugin (one Gmail account). IMAP IDLE wired in; auth via `password_cmd` + 1Password.
- **AP-SP3** — Migration script + OAuth + multi-account (3 accounts, 3 spaces).

Don't skip ahead. AP-SP1's storage adapter design depends on AP-SP0's `sidecar-schemas` package. AP-SP2 depends on AP-SP1's plugin contract.

Each sub-slice ends with a **hardware acceptance test** on the live AE → Lola → Qdrant → kb-query loop. Don't declare a sub-slice done until acceptance passes (matches infra's MVP acceptance pattern).

## Decisions Already Made

Before proposing alternatives to any of these, re-read the Decision Log in `ROADMAP.md`:

- AccountPilot is MailPilot renamed in place — no backward compatibility, hard cut, one-shot migration script
- Plugin contract: 5 lifecycle hooks (`setup`, `backfill`, `sync_once`, `daemon`, `teardown`) + event emission
- Xapian search stays inside the mail plugin (not core) — only the mail plugin uses it
- XDG-compliant config path: `~/.config/accountpilot/config.yaml`
- Operational state at `~/runtime/accountpilot/` (state.db, xapian/, secrets/, logs/, tmp/) — never synced
- WhatsApp = manual export only in v1; live sync deferred (whatsmeow ban risk)
- Calendar OAuth extends Gmail/Outlook OAuth scopes — one consent covers both
- Read-only in Phase 1 — agent-driven sends (mail/iMessage/Telegram) come in infra Phase 4

## Resolved Phase 1 Questions (closed 2026-05-01)

All seven gating questions closed. Full text + rationale in `ROADMAP.md` §Resolved Questions. One-liner each:

- **Q1** — Hard cut `mailpilot` → `accountpilot` in AP-SP1, no compat shim
- **Q2** — Implement owner-aware adapter in AP-SP1, log to `infra/specs/DELTAS.md`, amend `ARCHITECTURE.md` §6.13 post-acceptance
- **Q3** + **Q6** — AE is sole sync host for all 3 mail accounts through AP-SP3 (Lola never runs mail plugin for `aren`)
- **Q4** — `sidecar-schemas` is a subpackage at `infra/scripts/sidecar_schemas/`
- **Q5** — AP-SP2 uses `password_cmd` + 1Password; OAuth lands in AP-SP3
- **Q7** — `migrate-from-mailpilot` ships with `--dry-run`, `--limit N`, `--resume-from <checksum>`

## Working Conventions

- Dates: today is 2026-05-01. Use absolute YYYY-MM-DD in any docs you write.
- Plans: write to `~/Projects/infra/specs/plans/` (not in this repo) — matches infra plan convention. Naming: `YYYY-MM-DD-accountpilot-ap-spN.md`.
- Architecture decisions: log to `~/Projects/infra/specs/DELTAS.md` first; promote to `ARCHITECTURE.md` after acceptance.
- Documentation: use the `/docs-craft` skill when creating, updating, or auditing docs.
- The `infra` repo is currently in spec freeze (per `DELTAS.md` 2026-04-22) — non-editorial spec changes require explicit unfreeze. AccountPilot work generates findings in `DELTAS.md`, not direct spec rewrites.
- Tests: pytest + pytest-asyncio + pytest-cov. ruff + mypy + pre-commit already configured. Don't break the existing MailPilot test suite during AP-SP1 rename — migrate tests alongside the code.
- Per-machine git identity (from infra `CLAUDE_CODE_SPEC.md`): AE=aren, Lola=lola, Rakun=rakun, Tita=tita. Commits from this repo on AE go under `aren`.

## What This Repo Is Not

- Not a deployment system. Deployment (launchd plists, secrets bootstrap, sync agents) lives in `infra/configs/` and `infra/scripts/`.
- Not a knowledge base. The KB pipeline (ingest → embed → Qdrant → kb-query) lives in `infra/scripts/{ingest,embed,kb}/`. AccountPilot writes files; KB pipeline picks them up.
- Not a sidecar schema authority. `sidecar-schemas` (TBD in AP-SP0) lives in infra and is consumed by both AccountPilot and the KB pipeline.
- Not a daemon orchestrator. Each plugin runs under its own launchd job (e.g., `com.accountpilot.daemon`). AccountPilot's `daemon` command is the process; launchd manages lifecycle.
