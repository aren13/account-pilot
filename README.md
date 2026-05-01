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
