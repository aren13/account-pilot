# AccountPilot Architecture

> Implementation-level architecture for the AccountPilot repo. The fleet-level system spec is `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md`; the storage and sidecar contracts are in `~/Projects/infra/specs/ARCHITECTURE.md`. This document describes how this repo realizes those specs.
>
> **Last updated:** 2026-05-01

## Overview

AccountPilot is a unified account sync framework. It pulls content from external services (email, calendar, iMessage, Telegram, WhatsApp) into a per-machine, per-space knowledge base via a plugin architecture. The core handles configuration, event routing, space-aware storage, authentication, and CLI; plugins handle one external service each and emit typed events.

The framework is read-only in v1. Outbound writes (sending mail, replying on iMessage) come in a later infra phase.

## Component Layout

```
src/accountpilot/
├── core/
│   ├── config.py        # XDG config loader, schema validation, plugin enable list
│   ├── events.py        # Async event bus + typed event models
│   ├── router.py        # Space routing rules, fallback to unclassified
│   ├── storage.py       # Owner-aware storage adapter (sole writer)
│   ├── auth.py          # password_cmd + Keychain + OAuth file resolution
│   ├── cli.py           # Click root group; per-plugin subcommand registration
│   └── plugin.py        # AccountPilotPlugin base class
└── plugins/
    ├── mail/            # IMAP IDLE, SMTP, Xapian search, JWZ threading
    ├── calendar/        # Google Calendar API, Microsoft Graph
    ├── imessage/        # ~/Library/Messages/chat.db reader (Full Disk Access required)
    ├── telegram/        # Telethon client, per-chat opt-in
    └── whatsapp/        # Manual chat.txt + zip importer
```

The core has zero plugin imports. Plugins have zero cross-imports — they communicate only via the event bus.

## Plugin Contract

Every plugin subclasses `AccountPilotPlugin` and implements 5 lifecycle hooks:

| Hook | Purpose |
|------|---------|
| `setup()` | One-time provisioning: validate config, register event types, request OS permissions |
| `backfill()` | Bounded historical pull (default windows per source type) |
| `sync_once()` | Single sync pass; emits events for new items since last cursor |
| `daemon()` | Long-running process: IDLE, push subscriptions, fsevents, polling loops |
| `teardown()` | Clean shutdown: persist cursor, close connections |

Plugins emit typed events (`mail.new`, `calendar.event`, `message.new`, etc.) and never write files or query downstream systems. The storage adapter is the sole consumer that hits disk.

## Storage Model

AccountPilot is the *ingestion* half of the knowledge-base pipeline, not the seeding half. Its contract is `event in → file out`. A separate pipeline at `~/Projects/infra/scripts/embed/` reads the files AccountPilot writes, chunks and embeds them, and upserts vectors into Qdrant. AccountPilot has zero Qdrant code and never sees a vector.

### End-to-end workflow

```
┌──────────────────────────────────────────────────────────────────────┐
│  ACCOUNTPILOT                                                        │
│                                                                      │
│   external           plugin              core                        │
│   service          (mail, cal, …)                                    │
│   ┌──────┐         ┌─────────┐         ┌────────────┐               │
│   │Gmail │ IDLE    │  mail   │ emit    │ event bus  │               │
│   │ IMAP │────────▶│ plugin  │────────▶│            │               │
│   └──────┘         └─────────┘ mail.new└─────┬──────┘               │
│                                              │                       │
│                                              ▼                       │
│                                       ┌──────────────┐              │
│                                       │ storage      │              │
│                                       │ adapter      │              │
│                                       │              │              │
│                                       │ reads:       │              │
│                                       │ ~/spaces/    │              │
│                                       │  <space>/    │              │
│                                       │  meta.json   │              │
│                                       └──────┬───────┘              │
│                          owner == hostname ? │                       │
│                ┌─────────────────────────────┴─────┐                │
│                ▼ yes (local)                       ▼ no (non-owner) │
│       ~/spaces/<space>/                   ~/outbound/<space>/        │
│       data/emails/                        data/emails/               │
│       {date}_{hash}.eml                   {date}_{hash}.eml          │
│       {date}_{hash}.json                  {date}_{hash}.json         │
│                │                                   │                 │
└────────────────┼───────────────────────────────────┼─────────────────┘
                 │       AccountPilot ends here      │
─ ─ ─ ─ ─ ─ ─ ─ ─┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─┼─ ─ ─ ─ ─ ─ ─ ─ ─ ─
                 │       infra pipeline begins       │
                 │                            ┌──────▼────────┐
                 │                            │ outbound-     │
                 │                            │ watcher       │
                 │                            │ (launchd)     │
                 │                            └──────┬────────┘
                 │                                   │ Tailscale
                 │                                   ▼ rsync
                 │                            ┌───────────────┐
                 │                            │ inbound-      │
                 │                            │ ingest        │
                 │                            │ (owner host)  │
                 │                            └──────┬────────┘
                 │                                   │
                 │                                   ▼
                 │                          ~/spaces/<space>/
                 │                          data/emails/
                 │                                   │
                 └─────────────────┬─────────────────┘
                                   │
                       ┌───────────▼──────────────┐
                       │ embed pipeline            │
                       │ (infra/scripts/embed/)    │
                       │                           │
                       │ 1. read file + sidecar    │
                       │ 2. chunk content          │
                       │ 3. embed (Voyage/OpenAI)  │
                       │ 4. upsert to Qdrant       │
                       └───────────┬──────────────┘
                                   │
                                   ▼
                          ┌────────────────┐
                          │ qdrant-<space> │
                          │ on owner host  │
                          └────────┬───────┘
                                   │
                                   ▼
                          kb query (from any host
                          via federation proxy)
```

The dashed line is a transport boundary, not a metadata boundary. Sidecars are written by the storage adapter and consumed by the embed pipeline — they survive the whole journey and carry every field needed for chunking, source attribution, and parent linking.

### Owner-aware adapter

Each space has an owner host recorded in `~/spaces/<space>/meta.json` (defined by infra `ARCHITECTURE.md` §6.9). The storage adapter resolves the write path per event:

| Owner check | Write path |
|-------------|------------|
| `meta.json.owner == hostname` | `~/spaces/<space>/data/<source>/` |
| `meta.json.owner != hostname` | `~/outbound/<space>/data/<source>/` |
| `meta.json` missing | `~/inbox/unclassified/` + warning logged; never auto-guess |

Outbound files are picked up by the per-machine `outbound-watcher` launchd job (defined in infra) and shipped over Tailscale to the owner host, where `inbound-ingest` drops them into `~/spaces/<space>/data/<source>/`. The embed pipeline runs on the owner host only, since Qdrant is co-located with the space owner.

### File and sidecar contract

| Concern | Rule |
|---------|------|
| Filename | `{YYYYMMDD}_{hash6}.{ext}` per infra `ARCHITECTURE.md` §7 — adapter assigns; plugins never pick |
| Sidecar | One JSON sidecar per file, conforming to the matching `sidecar-schemas` model |
| Self-containment | Sidecars carry every metadata field needed to interpret the file; folder paths are not load-bearing |
| State | All written files are snapshots (`state: "snapshot"`); the live tree at `~/Documents/spaces/<space>/` is never touched by AccountPilot |
| Dedup | Adapter computes payload checksum; duplicate writes are skipped, making sync re-runs idempotent |

Sidecar Pydantic v2 models live in the infra repo at `~/Projects/infra/scripts/sidecar_schemas/` and are consumed both by AccountPilot's storage adapter and by infra's `scripts/ingest/` pipeline.

## Configuration

### Paths

| Purpose | Path |
|---------|------|
| User config | `~/.config/accountpilot/config.yaml` (XDG-compliant) |
| Operational state | `~/runtime/accountpilot/state.db` (cursors, dedup checksums, internal queues) |
| Search indexes | `~/runtime/accountpilot/xapian/` (mail plugin only) |
| Secrets | `~/runtime/accountpilot/secrets/` (per-machine, never synced, bootstrapped from 1Password) |
| Logs | `~/runtime/accountpilot/logs/` |
| Temp | `~/runtime/accountpilot/tmp/` |

`~/runtime/` is excluded from every sync mechanism on every host.

### Config schema

```yaml
plugins:
  mail:
    enabled: true
    accounts:
      - name: personal
        space: aren
        provider: gmail
        auth: password_cmd
        password_cmd: "op read op://Personal/gmail-personal/password"
      - name: fazla
        space: fazla
        provider: gmail
        auth: oauth
        oauth_token: ~/runtime/accountpilot/secrets/oauth/google/fazla.json
  calendar:
    enabled: false   # Phase 2
routing:
  default_space: unclassified
  rules:
    - match: { plugin: mail, account: personal }
      space: aren
```

## Authentication

| Method | Use case |
|--------|----------|
| `password_cmd` + 1Password | Default for IMAP/SMTP in AP-SP2; works with Gmail app passwords and Outlook basic auth |
| OAuth (Google, Microsoft) | Default from AP-SP3; required for Calendar; refresh tokens persisted at `~/runtime/accountpilot/secrets/oauth/<provider>/<account>.json` |
| macOS Keychain | Available via `auth.py` shim for plugins that need OS-level secret storage (iMessage Full Disk Access tokens, Telegram session keys) |

OAuth scopes are unified per provider — one Google consent covers both Gmail and Calendar.

## Space Routing

The router is rule-based and explicit. Rules match on `(plugin, account, ...)` and assign a `space_id`. Unmatched events go to `unclassified` and the file lands in `~/inbox/unclassified/` for manual classification. The router never auto-guesses a space — silent misrouting would corrupt isolation.

Space isolation is absolute: a `fazla` email never lands in `aren`, and vice versa. This invariant is enforced at the storage-adapter boundary, not at the plugin level.

## Process Model

Each plugin's `daemon()` runs as its own launchd job, defined in infra at `configs/machines/<host>/launchd/`. Job names use the pattern `com.accountpilot.<plugin>.daemon` (e.g., `com.accountpilot.mail.daemon`). launchd handles process supervision, restart, and log redirection; AccountPilot itself never forks or supervises.

For one-off operations:

| Command | Purpose |
|---------|---------|
| `accountpilot status` | Plugin states, last sync cursors, queue depths |
| `accountpilot sync` | One-shot sync across all enabled plugins |
| `accountpilot <plugin> sync` | One-shot sync for a single plugin |
| `accountpilot <plugin> backfill` | Historical pull within plugin-defined window |
| `accountpilot daemon` | Foreground daemon (used by launchd; rarely run by hand) |
| `accountpilot migrate-from-mailpilot` | One-shot migration with `--dry-run`, `--limit N`, `--resume-from <checksum>` |

## Deployment Topology

AccountPilot runs only on AE in v1. AE syncs all 3 mail accounts (personal → `aren`, fazla → `fazla`, cm → `cm`) and emits to its respective outbound directories. The space owners (Lola, Rakun, Tita) host the KB but do not run the mail plugin themselves; this avoids duplicate IMAP IDLE sessions on shared accounts and keeps OAuth state on a single machine.

Per-machine deployment for plugins that must run on the data source (iMessage on AE, Telegram on a session-holder) is described in `ACCOUNT_PILOT_SPEC.md` §16.

## Invariants

These rules are load-bearing. Violating any of them corrupts the trust model.

1. **Plugins never write storage.** Disk and downstream-system writes happen only in `core/storage.py`.
2. **Plugins never query Qdrant.** The KB pipeline (in infra) consumes the files AccountPilot writes; AccountPilot has no Qdrant dependency.
3. **Plugins never import each other.** Cross-plugin communication is event-bus only.
4. **Space isolation is absolute.** Unmatched routing goes to `unclassified`, never to a guessed space.
5. **Snapshots only.** AccountPilot writes archival snapshots; the live `~/Documents/spaces/<space>/` tree is owned by the user, not by AccountPilot.
6. **Filename and sidecar formats are adapter-controlled.** Plugins emit content + metadata; the adapter formats both.
7. **Sidecars are self-contained.** Folder paths are not authoritative metadata.
8. **Secrets stay outside the repo.** All credentials live under `~/runtime/accountpilot/secrets/`, bootstrapped from 1Password.
9. **State is never synced.** `~/runtime/accountpilot/` is per-machine and ephemeral by design.

## Upstream References

| Document | Authority |
|----------|-----------|
| `~/Projects/infra/specs/ACCOUNT_PILOT_SPEC.md` | Canonical AccountPilot system spec — plugin contract, deployment matrix, source-type semantics |
| `~/Projects/infra/specs/ARCHITECTURE.md` | Fleet-wide KB architecture — space model (§5), filename rules (§7), sidecar schemas (§8), cross-host transfer (§6.12), owner-aware storage (§6.13) |
| `~/Projects/infra/scripts/sidecar_schemas/` | Pydantic models for all source-type sidecars |
| `~/Projects/infra/specs/CLAUDE_CODE_SPEC.md` | Per-machine secrets bootstrap pattern |
