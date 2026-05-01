# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — 2026-05-02 (AP-SP1)

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

[Unreleased]: https://github.com/ae/mail-pilot/commits/main
