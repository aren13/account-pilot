# Query Syntax Reference

MailPilot uses Xapian full-text search with prefix support.

## Prefix Search

| Prefix | Description | Example |
|--------|-------------|---------|
| `from:` | Sender email | `from:alice@example.com` |
| `to:` | Recipient email | `to:bob@example.com` |
| `cc:` | CC recipient | `cc:team@example.com` |
| `subject:` | Subject words | `subject:meeting` |
| `tag:` | Message tag | `tag:urgent` |
| `folder:` | IMAP folder | `folder:INBOX` |
| `account:` | Account name | `account:personal` |
| `has:` | Message property | `has:attachment` |

## Boolean Operators

```
from:alice AND tag:urgent
from:alice OR from:bob
from:alice NOT tag:spam
```

Default operator is AND (terms without operators are ANDed together).

## Phrase Search

```
"exact phrase match"
```

## Wildcards

```
from:alice*
subject:meet*
```

## Examples

```bash
# Unread from a specific sender
mailpilot search "from:boss@company.com tag:unread"

# Emails with attachments this week
mailpilot search "has:attachment"

# Search in specific account and folder
mailpilot search "account:work folder:INBOX subject:invoice"

# Phrase search
mailpilot search '"quarterly report"'
```
