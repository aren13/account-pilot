# Roadmap: MailPilot

## Overview

Build a unified email engine for AI agents in 5 phases: start with project scaffolding and core infrastructure (config, models, database, IMAP client), add real-time sync and IDLE notifications, layer on Xapian full-text search and tagging, implement send/reply/forward CRUD, then wrap it all in a CLI and open-source packaging.

## Phases

- [ ] **Phase 1: Foundation** - Project scaffolding, config, models, database, IMAP client, email parser
- [ ] **Phase 2: Sync + IDLE** - Maildir sync engine, IMAP IDLE listener, daemon orchestrator, event system
- [ ] **Phase 3: Search + Tags** - Xapian indexer, query engine, JWZ threading, tag manager, auto-tag rules
- [ ] **Phase 4: Send + CRUD** - SMTP client, email composer, management operations
- [ ] **Phase 5: CLI + Open Source** - Full Click CLI, OpenClaw skill, open-source scaffolding

## Phase Details

### Phase 1: Foundation
**Goal**: Working project skeleton — config loads, models validate, database initializes, IMAP connects and fetches messages, parser extracts structured data from raw email
**Depends on**: Nothing (first phase)
**Plans**: 3 plans

Plans:
- [ ] 01-01: Project scaffolding + config system (pyproject.toml, pydantic config models, config loader with password_cmd support)
- [ ] 01-02: Data models + database (pydantic models for all entities, SQLite schema with migrations, mp_id generation)
- [ ] 01-03: IMAP client + email parser (async IMAP wrapper with connection pool, provider quirks, RFC822 parser with MIME decoding)

### Phase 2: Sync + IDLE
**Goal**: Real-time email awareness — Maildir sync (bidirectional), IMAP IDLE push notifications, daemon process, event system with webhooks
**Depends on**: Phase 1
**Plans**: 3 plans

Plans:
- [ ] 02-01: Maildir sync engine (full + incremental sync, bidirectional flag sync, UID-based deduplication)
- [ ] 02-02: IMAP IDLE listener + daemon (IDLE per folder/account, auto re-IDLE, reconnect, SIGTERM handling, periodic safety-net sync)
- [ ] 02-03: Event system (SQLite event log, webhook POST, Python callbacks, all event types)

### Phase 3: Search + Tags
**Goal**: Fast full-text search and flexible tagging — Xapian indexing with boolean terms, query parser with prefix support, JWZ threading, tag CRUD with auto-tag rules
**Depends on**: Phase 2
**Plans**: 3 plans

Plans:
- [ ] 03-01: Xapian indexer + query engine (TermGenerator, boolean terms, QueryParser with prefixes, BM25 ranking, snippets, spelling)
- [ ] 03-02: JWZ threading (References/In-Reply-To grouping, deterministic thread IDs, subject-based fallback)
- [ ] 03-03: Tag manager + auto-tag rules (SQLite tag CRUD, Xapian XTAG sync, config-driven rules, rule logging)

### Phase 4: Send + CRUD
**Goal**: Complete email operations — send, reply, forward, draft, plus mark read/unread, flag, move, copy, delete with IMAP+SQLite+Xapian consistency
**Depends on**: Phase 3
**Plans**: 2 plans

Plans:
- [ ] 04-01: SMTP client + email composer (async SMTP, compose new/reply/forward, In-Reply-To/References headers, save to Sent folder)
- [ ] 04-02: Management operations + MailPilot API class (mark read/unread, flag, move, copy, delete — each updates IMAP+SQLite+Xapian+event)

### Phase 5: CLI + Open Source
**Goal**: Ship it — full Click CLI with JSON/table output, OpenClaw skill definition, and complete open-source packaging (LICENSE, README, CI, templates)
**Depends on**: Phase 4
**Plans**: 2 plans

Plans:
- [ ] 05-01: Click CLI (all commands from spec: daemon, account, sync, search, send, management, tags, attachments, events, global flags)
- [ ] 05-02: Open-source scaffolding + OpenClaw skill (LICENSE, README, CONTRIBUTING, CHANGELOG, CODE_OF_CONDUCT, SECURITY, CI workflow, issue/PR templates, config.example.yaml, skill/SKILL.md)

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 0/3 | Not started | - |
| 2. Sync + IDLE | 0/3 | Not started | - |
| 3. Search + Tags | 0/3 | Not started | - |
| 4. Send + CRUD | 0/2 | Not started | - |
| 5. CLI + Open Source | 0/2 | Not started | - |
