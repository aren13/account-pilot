# Configuration Reference

MailPilot configuration lives at `~/.mailpilot/config.yaml`.

## Structure

```yaml
mailpilot:
  data_dir: "~/.mailpilot"      # Data directory
  log_level: "INFO"              # DEBUG, INFO, WARNING, ERROR
  log_format: "json"             # json or text
  log_file: null                 # Optional log file path

accounts:
  - name: "personal"             # Unique account identifier
    email: "you@gmail.com"
    display_name: "Your Name"    # Optional
    provider: "gmail"            # gmail, outlook, or custom
    imap:
      host: "imap.gmail.com"
      port: 993
      encryption: "tls"          # tls, starttls, or none
      auth:
        method: "password"       # password or oauth2
        password_cmd: "pass show email/gmail"
    smtp:
      host: "smtp.gmail.com"
      port: 587
      encryption: "starttls"
      auth:
        method: "password"
        password_cmd: "pass show email/gmail"
    folders:
      watch: ["INBOX"]           # Folders for IDLE monitoring
      sync: ["INBOX"]            # Folders to sync
      aliases:                   # Canonical → provider folder mapping
        sent: "[Gmail]/Sent Mail"
        trash: "[Gmail]/Trash"
    webhook_url: null             # Optional webhook for events

search:
  stemming: "english"
  spelling: true
  snippet_length: 200
  default_limit: 20

sync:
  idle_timeout: 1680             # Seconds before re-IDLE (< 29 min)
  reconnect_base_delay: 5
  reconnect_max_delay: 300
  full_sync_interval: 3600       # Periodic full sync (seconds)
  max_message_size: 52428800     # 50MB

rules:
  - name: "tag-github"
    match: "from:notifications@github.com"
    actions:
      - tag: "+github"
  - name: "tag-newsletters"
    match: "from:*@substack.com"
    actions:
      - tag: "+newsletter"
      - tag: "-inbox"
```

## Password Resolution

The `password_cmd` field runs a shell command and uses stdout as the password.
Compatible with password managers like `pass`, `1password-cli`, `op`, etc.

## Providers

- **gmail**: Auto-resolves `[Gmail]/Sent Mail`, `[Gmail]/Trash`, etc.
- **outlook**: Auto-resolves `Sent Items`, `Deleted Items`, etc.
- **custom**: No folder alias resolution; use exact IMAP folder names.
