# Roadmap: MailPilot

## Overview

Build a unified email engine for AI agents in 5 phases: start with project scaffolding and core infrastructure (config, models, database, IMAP client), add real-time sync and IDLE notifications, layer on Xapian full-text search and tagging, implement send/reply/forward CRUD, then wrap it all in a CLI and open-source packaging.

## Phases

- [x] **Phase 1: Foundation** - Project scaffolding, config, models, database, IMAP client, email parser
- [x] **Phase 2: Sync + IDLE** - Maildir sync engine, IMAP IDLE listener, daemon orchestrator, event system
- [x] **Phase 3: Search + Tags** - Xapian indexer, query engine, JWZ threading, tag manager, auto-tag rules
- [x] **Phase 4: Send + CRUD** - SMTP client, email composer, management operations
- [x] **Phase 5: CLI + Open Source** - Full Click CLI, OpenClaw skill, open-source scaffolding

## Phase Details

### Phase 1: Foundation
**Goal**: Working project skeleton — config loads, models validate, database initializes, IMAP connects and fetches messages, parser extracts structured data from raw email
**Depends on**: Nothing (first phase)
**Plans**: 3 plans

Plans:
- [x] 01-01: Project scaffolding + config system
- [x] 01-02: Data models + database
- [x] 01-03: IMAP client + email parser

### Phase 2: Sync + IDLE
**Goal**: Real-time email awareness — Maildir sync (bidirectional), IMAP IDLE push notifications, daemon process, event system with webhooks
**Depends on**: Phase 1
**Plans**: 3 plans

Plans:
- [x] 02-01: Maildir sync engine
- [x] 02-02: IMAP IDLE listener + daemon
- [x] 02-03: Event system

### Phase 3: Search + Tags
**Goal**: Fast full-text search and flexible tagging — Xapian indexing with boolean terms, query parser with prefix support, JWZ threading, tag CRUD with auto-tag rules
**Depends on**: Phase 2
**Plans**: 3 plans

Plans:
- [x] 03-01: Xapian indexer + query engine
- [x] 03-02: JWZ threading
- [x] 03-03: Tag manager + auto-tag rules

### Phase 4: Send + CRUD
**Goal**: Complete email operations — send, reply, forward, draft, plus mark read/unread, flag, move, copy, delete with IMAP+SQLite+Xapian consistency
**Depends on**: Phase 3
**Plans**: 2 plans

Plans:
- [x] 04-01: SMTP client + email composer
- [x] 04-02: Management operations + MailPilot API class

### Phase 5: CLI + Open Source
**Goal**: Ship it — full Click CLI with JSON/table output, OpenClaw skill definition, and complete open-source packaging
**Depends on**: Phase 4
**Plans**: 2 plans

Plans:
- [x] 05-01: Click CLI
- [x] 05-02: Open-source scaffolding + OpenClaw skill

## Progress

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete | 2026-04-02 |
| 2. Sync + IDLE | 3/3 | Complete | 2026-04-02 |
| 3. Search + Tags | 3/3 | Complete | 2026-04-02 |
| 4. Send + CRUD | 2/2 | Complete | 2026-04-02 |
| 5. CLI + Open Source | 2/2 | Complete | 2026-04-02 |
