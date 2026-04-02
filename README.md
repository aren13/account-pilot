# MailPilot

**Real-time email engine for AI agents.**

[![PyPI](https://img.shields.io/pypi/v/mailpilot)](https://pypi.org/project/mailpilot/)
[![CI](https://github.com/ae/mail-pilot/actions/workflows/ci.yml/badge.svg)](https://github.com/ae/mail-pilot/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/ae/mail-pilot)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/mailpilot)](https://pypi.org/project/mailpilot/)

---

## Why MailPilot?

Existing CLI email stacks require stitching together three or more tools:
**mbsync** for IMAP sync, **notmuch** for indexing, and **himalaya** (or mutt/neomutt)
for reading and sending. Each has its own config format, its own data store,
and its own failure modes. Wiring them together into an AI agent workflow means
writing brittle glue code across all of them.

MailPilot replaces that entire stack with a single async Python library and CLI.
One config file. One process. Real-time IMAP IDLE push, full-text Xapian search,
CRUD operations, tagging, rules, and SMTP sending -- all accessible as a Python
API or from the command line.

## Features

- **IMAP IDLE push** -- real-time notifications when new mail arrives, no polling
- **Xapian full-text search** -- fast, stemmed, with spelling correction
- **Email CRUD** -- read, move, copy, delete, flag, and archive messages
- **Tagging and auto-tag rules** -- flexible tag system with rule-based automation
- **SMTP sending** -- compose and send directly, with drafts support
- **Thread reconstruction** -- JWZ algorithm for accurate conversation threading
- **Multi-account** -- manage personal and work accounts from one config
- **CLI and Python API** -- use from the terminal or import as an async library
- **SQLite metadata store** -- lightweight, zero-config local database
- **Event system** -- hook into new-message, sync, and tag events

## Quickstart

```bash
pip install mailpilot
```

Copy the example config and edit it for your accounts:

```bash
mkdir -p ~/.mailpilot
cp config.example.yaml ~/.mailpilot/config.yaml
# Edit ~/.mailpilot/config.yaml with your IMAP/SMTP credentials
```

Sync your mailbox:

```bash
mailpilot sync
```

## Usage

```bash
# List recent messages
mailpilot list --limit 20

# Search messages
mailpilot search "from:alice subject:meeting"

# Read a message
mailpilot read <message-id>

# Send an email
mailpilot send --to alice@example.com --subject "Hello" --body "Hi Alice!"

# Tag messages
mailpilot tag +urgent <message-id>

# Start IDLE daemon (real-time push)
mailpilot daemon

# Show account status
mailpilot status
```

## Configuration

MailPilot uses a single YAML config file at `~/.mailpilot/config.yaml`.
See [`config.example.yaml`](config.example.yaml) for a fully annotated reference.

Key sections:

| Section    | Purpose                                      |
|------------|----------------------------------------------|
| `mailpilot`| Global settings: data dir, logging           |
| `accounts` | IMAP/SMTP credentials, folders, providers    |
| `search`   | Xapian stemming, spelling, snippet settings  |
| `sync`     | IDLE timeout, reconnect, full sync interval  |
| `rules`    | Auto-tagging rules with match expressions    |

Passwords are never stored in the config file. Use `password_cmd` to resolve
credentials from your system keychain or a secret manager at runtime.

## Python API

```python
import asyncio
from mailpilot import MailPilot

async def main():
    mp = await MailPilot.from_config("~/.mailpilot/config.yaml")

    # Search messages
    results = await mp.search("from:alice is:unread", limit=10)
    for msg in results:
        print(f"{msg.date} {msg.sender} -- {msg.subject}")

    # Send an email
    await mp.send(
        account="personal",
        to=["bob@example.com"],
        subject="Hello from MailPilot",
        body="Sent via the async Python API.",
    )

    # Tag a message
    await mp.tag(msg.id, add=["+important", "+followup"])

asyncio.run(main())
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│                   CLI (Click)                    │
└────────────────────┬────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────┐
│               MailPilot API                      │
│  (async Python interface to all subsystems)      │
└──┬──────┬──────────┬──────────┬────────────┬────┘
   │      │          │          │            │
   ▼      ▼          ▼          ▼            ▼
┌─────┐┌─────┐┌──────────┐┌────────┐┌────────────┐
│IMAP ││SMTP ││  SQLite   ││ Xapian ││   Tags /   │
│IDLE ││Send ││ Metadata  ││ Search ││   Rules    │
└──┬──┘└──┬──┘└────┬─────┘└───┬────┘└────────────┘
   │      │        │          │
   ▼      ▼        ▼          ▼
 Mail   Mail    ~/.mailpilot/  ~/.mailpilot/
Server  Server   mail.db       xapian/
```

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) for
development setup, code style, testing, and the pull request process.

## License

MailPilot is licensed under the [Apache License 2.0](LICENSE).
