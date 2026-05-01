-- Identity layer ----------------------------------------------------------

CREATE TABLE people (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    surname     TEXT,
    is_owner    INTEGER NOT NULL DEFAULT 0,
    notes       TEXT,
    created_at  TIMESTAMP NOT NULL,
    updated_at  TIMESTAMP NOT NULL
);

CREATE TABLE identifiers (
    id          INTEGER PRIMARY KEY,
    person_id   INTEGER NOT NULL REFERENCES people(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    value       TEXT NOT NULL,
    is_primary  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMP NOT NULL,
    UNIQUE (kind, value)
);
CREATE INDEX idx_identifiers_person ON identifiers(person_id);

CREATE TABLE accounts (
    id                  INTEGER PRIMARY KEY,
    owner_id            INTEGER NOT NULL REFERENCES people(id),
    source              TEXT NOT NULL,
    account_identifier  TEXT NOT NULL,
    display_name        TEXT,
    credentials_ref     TEXT,
    enabled             INTEGER NOT NULL DEFAULT 1,
    backfilled_at       TIMESTAMP,
    created_at          TIMESTAMP NOT NULL,
    updated_at          TIMESTAMP NOT NULL,
    UNIQUE (source, account_identifier)
);
CREATE INDEX idx_accounts_owner ON accounts(owner_id);

-- Message layer -----------------------------------------------------------

CREATE TABLE messages (
    id           INTEGER PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    thread_id    TEXT,
    sent_at      TIMESTAMP NOT NULL,
    received_at  TIMESTAMP,
    body_text    TEXT NOT NULL DEFAULT '',
    body_html    TEXT,
    direction    TEXT NOT NULL,
    created_at   TIMESTAMP NOT NULL,
    UNIQUE (account_id, external_id)
);
CREATE INDEX idx_messages_thread  ON messages(thread_id);
CREATE INDEX idx_messages_sent_at ON messages(sent_at);
CREATE INDEX idx_messages_account ON messages(account_id);

CREATE TABLE email_details (
    message_id        INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    subject           TEXT NOT NULL DEFAULT '',
    in_reply_to       TEXT,
    references_json   TEXT,
    imap_uid          INTEGER NOT NULL,
    mailbox           TEXT NOT NULL,
    gmail_thread_id   TEXT,
    labels_json       TEXT,
    raw_headers_json  TEXT
);

CREATE TABLE imessage_details (
    message_id   INTEGER PRIMARY KEY REFERENCES messages(id) ON DELETE CASCADE,
    chat_guid    TEXT NOT NULL,
    service      TEXT NOT NULL,
    is_from_me   INTEGER NOT NULL,
    is_read      INTEGER NOT NULL DEFAULT 0,
    date_read    TIMESTAMP
);

CREATE TABLE message_people (
    message_id   INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    person_id    INTEGER NOT NULL REFERENCES people(id),
    role         TEXT NOT NULL,
    PRIMARY KEY (message_id, person_id, role)
);
CREATE INDEX idx_message_people_person ON message_people(person_id);

CREATE TABLE attachments (
    id            INTEGER PRIMARY KEY,
    message_id    INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    filename      TEXT NOT NULL,
    content_hash  TEXT NOT NULL,
    mime_type     TEXT,
    size_bytes    INTEGER NOT NULL,
    cas_path      TEXT NOT NULL
);
CREATE INDEX idx_attachments_message ON attachments(message_id);
CREATE INDEX idx_attachments_hash    ON attachments(content_hash);

-- Search layer ------------------------------------------------------------

CREATE VIRTUAL TABLE messages_fts USING fts5(
    body_text,
    subject,
    tokenize = 'porter unicode61'
);

CREATE TRIGGER messages_fts_insert
AFTER INSERT ON messages
BEGIN
    INSERT INTO messages_fts(rowid, body_text, subject)
    VALUES (NEW.id, NEW.body_text, '');
END;

CREATE TRIGGER messages_fts_update_body
AFTER UPDATE OF body_text ON messages
BEGIN
    UPDATE messages_fts SET body_text = NEW.body_text WHERE rowid = NEW.id;
END;

CREATE TRIGGER messages_fts_delete
AFTER DELETE ON messages
BEGIN
    DELETE FROM messages_fts WHERE rowid = OLD.id;
END;

CREATE TRIGGER email_details_fts_insert
AFTER INSERT ON email_details
BEGIN
    UPDATE messages_fts SET subject = NEW.subject WHERE rowid = NEW.message_id;
END;

CREATE TRIGGER email_details_fts_update
AFTER UPDATE OF subject ON email_details
BEGIN
    UPDATE messages_fts SET subject = NEW.subject WHERE rowid = NEW.message_id;
END;

-- Operational state -------------------------------------------------------

CREATE TABLE sync_status (
    account_id            INTEGER PRIMARY KEY REFERENCES accounts(id) ON DELETE CASCADE,
    last_sync_at          TIMESTAMP,
    last_success_at       TIMESTAMP,
    last_error            TEXT,
    last_error_at         TIMESTAMP,
    messages_ingested     INTEGER NOT NULL DEFAULT 0
);
