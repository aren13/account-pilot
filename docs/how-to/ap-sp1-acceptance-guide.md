# AP-SP1 Hardware Acceptance Guide

> **Last updated:** 2026-05-02
> **Status:** Active
> **Audience:** Maintainer (AE) running the seven hardware acceptance scenarios for sub-slice AP-SP1.

## Overview

Use this guide to run the seven hardware acceptance scenarios that gate AP-SP1 on AE. Scenarios 6 and 7 are deterministic and can be verified autonomously; scenarios 1 through 5 require a real Gmail account, real network, and a 24-hour soak window.

After all seven pass, tag the slice and move to AP-SP2 (iMessage plugin). If any fail, file a follow-up entry in `docs/plans/2026-05-02-accountpilot-ap-sp1.md` and fix before tagging.

The plan that defines these scenarios: `docs/plans/2026-05-02-accountpilot-ap-sp1.md` Task 18.
The spec that owns them: `docs/specs/2026-05-01-storage-rewrite-design.md` §7.2.

## Prerequisites

- macOS host running on AE.
- A Gmail account with two-factor authentication enabled (required to generate an app password).
- A second device or email account from which to send test messages.
- AccountPilot installed and on the path. Verify:
  ```bash
  which accountpilot
  accountpilot --version
  ```
- Built-in `security` (macOS Keychain CLI), `sqlite3`, and `networksetup`. All ship with macOS.

## Step 1: Stash the Gmail app password in macOS Keychain

Generate a Gmail app password at <https://myaccount.google.com/apppasswords>. The result is a 16-character string.

Store it in Keychain under a stable label so the daemon can retrieve it without prompts:

```bash
security add-generic-password \
  -a ardaeren13@gmail.com \
  -s accountpilot-gmail \
  -w '<paste-16-char-app-password-here>' \
  -U
```

Verify retrieval:

```bash
security find-generic-password -a ardaeren13@gmail.com -s accountpilot-gmail -w
```

Expected output: the 16-character app password printed to stdout.

The first time another process reads this item, macOS prompts for permission. Click **Always Allow** so the daemon does not hang on a GUI prompt later.

## Step 2: Write the config file

```bash
mkdir -p ~/.config/accountpilot ~/runtime/accountpilot/logs

cat > ~/.config/accountpilot/config.yaml <<'EOF'
version: 1

owners:
  - name: Arda
    surname: Eren
    identifiers:
      - { kind: email, value: ardaeren13@gmail.com }

plugins:
  mail:
    enabled: true
    accounts:
      - identifier: ardaeren13@gmail.com
        owner: ardaeren13@gmail.com
        provider: gmail
        credentials_ref: "password_cmd:security find-generic-password -a ardaeren13@gmail.com -s accountpilot-gmail -w"
EOF
```

## Step 3: Apply the config to the database

```bash
accountpilot setup
accountpilot status
```

The status output lists one row showing source `gmail`, your Gmail address, owner `'Arda Eren'`, `messages=0`, `last_sync=—`. Note the `account_id` (likely `1`):

```bash
ACCOUNT_ID=1   # adjust if status shows a different id
```

## Step 4: Run scenario 1 — new email arrives via the daemon

### 4.1 One-shot backfill to seed the watermark

```bash
accountpilot mail backfill $ACCOUNT_ID
```

This pulls existing INBOX history. On a busy inbox it takes several minutes. Re-running is idempotent so partial pulls are safe to interrupt.

### 4.2 Start the daemon in terminal A

```bash
accountpilot mail daemon
```

Leave it running. The log emits one line per cycle: `sync_once account=1 mailbox=INBOX inserted=N skipped=M`.

### 4.3 Trigger a fresh email

From a second device or account, send the test mailbox a message containing a unique phrase, for example `AP-SP1 acceptance pingback ZULU-2026`.

### 4.4 Verify the message lands

In terminal B:

```bash
accountpilot mail sync $ACCOUNT_ID
accountpilot search 'ZULU-2026'
```

Expected: at least one hit formatted `[gmail] <sent_at>  <subject>  (id=<N>)`.

The sub-five-second IDLE-latency target lands fully in AP-SP2. AP-SP1's daemon polls on a `idle_timeout_seconds` cycle (default 1740). To shorten the loop for testing, lower the value in `config.yaml` and restart the daemon:

```yaml
plugins:
  mail:
    idle_timeout_seconds: 30
```

**Pass criteria:** search returns the test email after sync. Note the wall time and which path you used (manual sync versus daemon poll).

## Step 5: Run scenario 2 — attachment lands in CAS

### 5.1 Send yourself an email with an attachment

Use a different unique phrase, for example `AP-SP1 attachment test ECHO-2026`. Any file type works.

### 5.2 Sync

```bash
accountpilot mail sync $ACCOUNT_ID
```

### 5.3 Read the attachments row

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db <<'SQL'
.headers on
.mode column
SELECT a.id, a.filename, a.mime_type, a.size_bytes, a.content_hash, a.cas_path
FROM attachments a
JOIN messages m ON m.id = a.message_id
JOIN email_details ed ON ed.message_id = m.id
WHERE ed.subject LIKE '%ECHO-2026%'
ORDER BY a.id DESC
LIMIT 5;
SQL
```

### 5.4 Verify the file on disk and the hash match

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db \
  "SELECT cas_path, content_hash FROM attachments ORDER BY id DESC LIMIT 1" \
  | while IFS='|' read REL HASH; do
      FULL=~/runtime/accountpilot/attachments/"$REL"
      ls -la "$FULL"
      echo "expected sha256: $HASH"
      echo "actual sha256:   $(shasum -a 256 "$FULL" | cut -d' ' -f1)"
    done
```

**Pass criteria:** the file exists at `~/runtime/accountpilot/attachments/<h[:2]>/<h[2:4]>/<h>.bin`, and the expected sha256 matches the actual sha256.

## Step 6: Run scenario 3 — senders resolve to people rows

```bash
accountpilot people list | head -20
```

Expected: one line per unique sender encountered during backfill or sync. The owner row carries the `*` flag.

Spot-check that no duplicate person rows exist for the same address:

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db <<'SQL'
SELECT i.value, COUNT(DISTINCT i.person_id) AS person_count
FROM identifiers i
GROUP BY i.kind, i.value
HAVING person_count > 1;
SQL
```

**Pass criteria:** the spot-check query returns zero rows.

## Step 7: Run scenario 4 — search ranks correctly

Step 4.4 already exercises one search query. As a broader check, run two more against phrases you expect to be in your mail:

```bash
accountpilot search 'attachment' --limit 5
accountpilot search 'invoice' --limit 5
```

**Pass criteria:** results are real emails containing the phrase, ordered by `sent_at` descending.

## Step 8: Run scenario 5 — 24-hour soak with network blip

### 8.1 Optional: deploy via launchd

A launchd plist already lives in the infra repo at `~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist` (commit `ddc7c79`, not yet pushed). Bootstrap it:

```bash
launchctl bootstrap gui/$UID ~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist
launchctl enable gui/$UID/com.accountpilot.mail.daemon
launchctl kickstart gui/$UID/com.accountpilot.mail.daemon

launchctl print gui/$UID/com.accountpilot.mail.daemon | head -30
tail -f ~/runtime/accountpilot/logs/mail.daemon.stdout.log
```

If the plist's `ProgramArguments[0]` does not match where `accountpilot` actually lives on this machine, edit the plist to point at the correct path before bootstrap.

If you skip launchd: leave `accountpilot mail daemon` running in a `tmux` session.

### 8.2 Note the start state

```bash
date
sqlite3 ~/runtime/accountpilot/accountpilot.db \
  "SELECT COUNT(*) AS total, COUNT(DISTINCT external_id) AS unique_msgids \
   FROM messages WHERE account_id=$ACCOUNT_ID"
```

### 8.3 Trigger a deliberate network blip mid-run

Roughly halfway through the 24-hour window, toggle wifi off for 30 seconds:

```bash
networksetup -setairportpower en0 off
sleep 30
networksetup -setairportpower en0 on
```

Watch the daemon log for the next sync cycle:

```bash
tail -50 ~/runtime/accountpilot/logs/mail.daemon.stdout.log
```

A logged exception followed by a successful retry on the next cycle is acceptable.

### 8.4 Verify after 24 hours

```bash
date
accountpilot status
sqlite3 ~/runtime/accountpilot/accountpilot.db \
  "SELECT COUNT(*) AS total, COUNT(DISTINCT external_id) AS unique_msgids \
   FROM messages WHERE account_id=$ACCOUNT_ID"
```

**Pass criteria:**

- `last_sync_at` in `accountpilot status` is within the last `idle_timeout_seconds` window.
- `last_error` is empty or shows a transient error from the deliberate blip that recovered.
- `total` equals `unique_msgids` (no duplicate ingestion).

### 8.5 Stop the daemon

If you used launchd:

```bash
launchctl bootout gui/$UID/com.accountpilot.mail.daemon
```

If you used `tmux`: send `Ctrl-C` to the daemon pane.

## Step 9: Tag the slice

Scenarios 6 and 7 are already verified.

When 1 through 5 also pass, tag the commit:

```bash
cd ~/Code/account-pilot
git tag -a ap-sp1-complete -m "$(cat <<'EOF'
AP-SP1 acceptance passed on AE.

7/7 hardware scenarios verified per spec §7.2:
1. New email -> search returns it (path: <sync|daemon-poll>; <wall time>).
2. Attachment-bearing email -> CAS file exists, sha256 matches.
3. Senders resolve to a single people row each (no duplicates).
4. Search across mail returns the right matches.
5. Daemon 24h soak; network blip recovery; total == unique_msgids.
6. src/mailpilot/ deleted; git grep clean of live references.
7. setup idempotent against config.yaml.

Next slice: AP-SP2 (iMessage plugin).
EOF
)"
git push origin ap-sp1-complete
```

Then push the launchd plist commit if you are ready to publish it:

```bash
cd ~/Projects/infra
git push origin main
```

## Troubleshooting

### Daemon connect fails with "AUTHENTICATIONFAILED"

The Keychain item is missing or the app password expired. Re-run:

```bash
security find-generic-password -a ardaeren13@gmail.com -s accountpilot-gmail -w
```

If empty, regenerate the app password and re-run Step 1. Restart the daemon.

### macOS prompts for Keychain access on every read

You did not click **Always Allow** the first time. Run `accountpilot mail sync $ACCOUNT_ID` in a foreground shell once to surface the prompt with a TTY attached, then click **Always Allow**.

### `accountpilot mail sync` shows a raw FileNotFoundError when --config points at a missing file

Known cosmetic issue scheduled for AP-SP3 polish. The exit code is non-zero and the error is correct; the format is not yet wrapped in a clean `UsageError`.

### `total` does not equal `unique_msgids` after the soak

Filter the duplicates and inspect:

```bash
sqlite3 ~/runtime/accountpilot/accountpilot.db <<'SQL'
SELECT external_id, COUNT(*) AS c
FROM messages
WHERE account_id = $ACCOUNT_ID
GROUP BY external_id
HAVING c > 1
LIMIT 20;
SQL
```

If duplicates exist, the dedup invariant is broken. Open a follow-up in the SP1 plan with the offending `external_id` values and the timestamps of both rows.

## Related documents

- `docs/plans/2026-05-02-accountpilot-ap-sp1.md` — the AP-SP1 implementation plan, including Task 18 acceptance scenarios.
- `docs/specs/2026-05-01-storage-rewrite-design.md` — design spec, §7.2 lists the seven scenarios.
- `~/Projects/infra/configs/machines/ae/launchd/com.accountpilot.mail.daemon.plist` — the launchd plist for Step 8.1.
- `CHANGELOG.md` — AP-SP1 entry summarizing the slice.
