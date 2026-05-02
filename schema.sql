-- Enron Email Pipeline — SQLite Schema

CREATE TABLE IF NOT EXISTS emails (
    message_id          TEXT PRIMARY KEY,
    date                TEXT NOT NULL,              -- ISO 8601 UTC
    from_address        TEXT NOT NULL,
    subject             TEXT NOT NULL DEFAULT '',
    subject_normalized  TEXT NOT NULL DEFAULT '',
    body                TEXT NOT NULL DEFAULT '',
    source_file         TEXT NOT NULL,
    x_from              TEXT,
    x_to                TEXT,
    x_cc                TEXT,
    x_bcc               TEXT,
    x_folder            TEXT,
    x_origin            TEXT,
    content_type        TEXT,
    has_attachment      INTEGER NOT NULL DEFAULT 0, -- BOOLEAN: 0/1
    forwarded_content   TEXT,
    quoted_content      TEXT,
    headings            TEXT,
    -- duplicate detection columns
    is_duplicate        INTEGER NOT NULL DEFAULT 0, -- BOOLEAN: 0/1
    duplicate_of        TEXT REFERENCES emails(message_id),
    similarity_score    REAL,
    -- notification columns
    notification_sent   INTEGER NOT NULL DEFAULT 0, -- BOOLEAN: 0/1
    notification_date   TEXT                        -- ISO 8601 UTC
);

-- Normalized address tables (to/cc/bcc stored here, not as CSV strings)
CREATE TABLE IF NOT EXISTS email_recipients (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id  TEXT NOT NULL REFERENCES emails(message_id) ON DELETE CASCADE,
    field       TEXT NOT NULL CHECK(field IN ('to', 'cc', 'bcc')),
    address     TEXT NOT NULL
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_emails_date          ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_from_address  ON emails(from_address);
CREATE INDEX IF NOT EXISTS idx_emails_subject_norm  ON emails(subject_normalized);
CREATE INDEX IF NOT EXISTS idx_emails_is_duplicate  ON emails(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_recipients_message   ON email_recipients(message_id);
CREATE INDEX IF NOT EXISTS idx_recipients_address   ON email_recipients(address);
