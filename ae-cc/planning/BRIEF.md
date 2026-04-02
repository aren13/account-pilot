# MailPilot

**One-liner**: Real-time email engine for AI agents — one tool to replace mbsync + notmuch + himalaya.

## Problem

Managing email programmatically for AI agents requires stitching together 3+ tools (mbsync for sync, notmuch for search, himalaya for CRUD), each with separate configs, binaries, and limitations. The result is fragile glue scripts, 2-5 minute notification latency, and no single tool an agent can call for everything.

MailPilot solves this by being one Python tool that does all three jobs — plus real-time IMAP IDLE, Xapian full-text search, a flexible tagging system, and a clean JSON API designed for LLM agents.

## Success Criteria

- [ ] Single `pip install mailpilot` replaces mbsync + notmuch + himalaya
- [ ] IMAP IDLE delivers sub-2-second new mail notifications
- [ ] Xapian search returns results in <100ms on 100k+ messages
- [ ] Full email CRUD (search, read, send, reply, forward, tag, delete) via CLI and Python API
- [ ] All output is JSON — designed for agent consumption
- [ ] Works with Gmail, Outlook, and any IMAP/SMTP provider

## Constraints

- Python 3.11+ (async throughout with asyncio)
- System dependency: xapian-core + python3-xapian bindings
- Single-user, single-machine (no multi-tenancy)
- Apache 2.0 license (matching OpenClaw)
- Primary integration target: OpenClaw P0 agent via ClawHub skill

## Out of Scope

- GUI / TUI (headless, agent-first)
- CalDAV / CardDAV (email only)
- POP3 (IMAP only)
- HTML email rendering (agents read plain text)
- Spam filtering (use server-side filters)
- Multi-user support
