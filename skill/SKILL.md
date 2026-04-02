# MailPilot

**Real-time email engine for AI agents.**

## Metadata

- **Name**: mailpilot
- **Version**: 0.1.0
- **License**: Apache-2.0
- **Python**: >=3.11

## Prerequisites

- Python 3.11+
- Optional: xapian-core + python3-xapian (for full-text search)

## Installation

```bash
pip install mailpilot
```

## Configuration

Create `~/.mailpilot/config.yaml`. See [configuration reference](references/configuration.md).

## Available Commands

| Command | Description |
|---------|-------------|
| `mailpilot start` | Start the daemon (IDLE + periodic sync) |
| `mailpilot stop` | Stop the daemon |
| `mailpilot status` | Show daemon status |
| `mailpilot sync [account]` | Force sync all or specific account |
| `mailpilot search QUERY` | Full-text search with prefix support |
| `mailpilot show MP_ID` | Show full message with body |
| `mailpilot thread THREAD_ID` | Show conversation thread |
| `mailpilot unread` | List unread messages |
| `mailpilot count QUERY` | Count matching messages |
| `mailpilot send` | Send a new email |
| `mailpilot reply MP_ID` | Reply to a message |
| `mailpilot forward MP_ID` | Forward a message |
| `mailpilot read MP_IDS...` | Mark messages as read |
| `mailpilot flag MP_IDS...` | Flag messages |
| `mailpilot move MP_IDS... --to FOLDER` | Move messages |
| `mailpilot delete MP_IDS...` | Delete messages |
| `mailpilot tag add TAG MP_IDS...` | Add tag to messages |
| `mailpilot tag list` | List all tags with counts |
| `mailpilot events` | List recent events |

All commands output JSON by default. Use `-o table` for human-readable output.

## Agent Usage Patterns

### Check inbox
```bash
mailpilot unread --limit 10
```

### Search and reply
```bash
mailpilot search "from:boss@company.com subject:urgent"
mailpilot reply mp-000042 --body "I'll handle this right away."
```

### Tag and organize
```bash
mailpilot tag add reviewed mp-000042 mp-000043
mailpilot search "tag:reviewed"
```

## Query Syntax

See [query syntax reference](references/query-syntax.md) for full documentation.
