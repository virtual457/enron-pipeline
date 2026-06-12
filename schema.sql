CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    email        TEXT NOT NULL UNIQUE,
    display_name TEXT
);

CREATE TABLE IF NOT EXISTS emails (
    message_id        TEXT PRIMARY KEY,
    date              TEXT NOT NULL,
    from_user_id      INTEGER NOT NULL REFERENCES users(user_id),
    subject           TEXT,
    body              TEXT,
    source_file       TEXT,
    x_from            TEXT,
    x_to              TEXT,
    x_cc              TEXT,
    x_bcc             TEXT,
    x_folder          TEXT,
    x_origin          TEXT,
    content_type      TEXT,
    has_attachment    INTEGER DEFAULT 0,
    forwarded_content TEXT,
    quoted_content    TEXT,
    headings          TEXT,
    similarity_score  REAL,
    is_duplicate      INTEGER DEFAULT 0 CHECK(is_duplicate IN (0, 1)),
    duplicate_of      TEXT REFERENCES emails(message_id)
                      CHECK(
                          (is_duplicate = 0 AND duplicate_of IS NULL) OR
                          (is_duplicate = 1 AND duplicate_of IS NOT NULL)
                      ),
    notification_sent INTEGER DEFAULT 0,
    notification_date TEXT
);

CREATE TABLE IF NOT EXISTS email_recipients (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL REFERENCES emails(message_id),
    user_id    INTEGER NOT NULL REFERENCES users(user_id),
    type       TEXT NOT NULL CHECK(type IN ('to','cc','bcc'))
);

CREATE INDEX IF NOT EXISTS idx_emails_date         ON emails(date);
CREATE INDEX IF NOT EXISTS idx_emails_subject      ON emails(subject);
CREATE INDEX IF NOT EXISTS idx_emails_from_user    ON emails(from_user_id);
CREATE INDEX IF NOT EXISTS idx_emails_is_duplicate ON emails(is_duplicate);
CREATE INDEX IF NOT EXISTS idx_recipients_msg      ON email_recipients(message_id);
CREATE INDEX IF NOT EXISTS idx_recipients_user     ON email_recipients(user_id);
CREATE INDEX IF NOT EXISTS idx_users_email         ON users(email);
