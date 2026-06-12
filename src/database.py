import os
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "schema.sql")


def get_connection(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str) -> sqlite3.Connection:
    conn = get_connection(db_path)
    schema = Path(SCHEMA_PATH).read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.commit()
    return conn


def get_or_create_user(conn: sqlite3.Connection, email: str, display_name: str = None) -> int:
    """Return user_id for email, inserting if not exists."""
    cur = conn.execute("SELECT user_id FROM users WHERE email = ?", (email,))
    row = cur.fetchone()
    if row:
        return row["user_id"]
    cur = conn.execute(
        "INSERT INTO users (email, display_name) VALUES (?, ?)",
        (email, display_name),
    )
    return cur.lastrowid


def insert_email(conn: sqlite3.Connection, record: dict) -> bool:
    """
    Insert one parsed email record.
    Returns True if inserted, False if skipped (duplicate message_id).
    """
    from_user_id = get_or_create_user(conn, record["from_address"], record.get("x_from"))

    try:
        conn.execute(
            """
            INSERT INTO emails (
                message_id, date, from_user_id, subject, body, source_file,
                x_from, x_to, x_cc, x_bcc, x_folder, x_origin,
                content_type, has_attachment, forwarded_content, quoted_content, headings
            ) VALUES (
                :message_id, :date, :from_user_id, :subject, :body, :source_file,
                :x_from, :x_to, :x_cc, :x_bcc, :x_folder, :x_origin,
                :content_type, :has_attachment, :forwarded_content, :quoted_content, :headings
            )
            """,
            {
                "message_id": record["message_id"],
                "date": record["date"],
                "from_user_id": from_user_id,
                "subject": record.get("subject"),
                "body": record.get("body"),
                "source_file": record.get("source_file"),
                "x_from": record.get("x_from"),
                "x_to": record.get("x_to"),
                "x_cc": record.get("x_cc"),
                "x_bcc": record.get("x_bcc"),
                "x_folder": record.get("x_folder"),
                "x_origin": record.get("x_origin"),
                "content_type": record.get("content_type"),
                "has_attachment": int(record.get("has_attachment", False)),
                "forwarded_content": record.get("forwarded_content"),
                "quoted_content": record.get("quoted_content"),
                "headings": record.get("headings"),
            },
        )
    except sqlite3.IntegrityError:
        return False

    for addr in record.get("to_addresses", []):
        uid = get_or_create_user(conn, addr)
        conn.execute(
            "INSERT INTO email_recipients (message_id, user_id, type) VALUES (?, ?, 'to')",
            (record["message_id"], uid),
        )
    for addr in record.get("cc_addresses", []):
        uid = get_or_create_user(conn, addr)
        conn.execute(
            "INSERT INTO email_recipients (message_id, user_id, type) VALUES (?, ?, 'cc')",
            (record["message_id"], uid),
        )
    for addr in record.get("bcc_addresses", []):
        uid = get_or_create_user(conn, addr)
        conn.execute(
            "INSERT INTO email_recipients (message_id, user_id, type) VALUES (?, ?, 'bcc')",
            (record["message_id"], uid),
        )

    return True


def insert_emails(conn: sqlite3.Connection, records: list[dict]) -> dict:
    """Bulk insert records. Returns stats dict."""
    inserted = 0
    skipped = 0
    total = len(records)
    for record in records:
        if insert_email(conn, record):
            inserted += 1
        else:
            skipped += 1
        if (inserted + skipped) % 1000 == 0:
            conn.commit()
            print(f"  Stored {inserted + skipped}/{total}...", flush=True)
    conn.commit()
    print(f"\n=== Storage Stats ===")
    print(f"Inserted : {inserted}")
    print(f"Skipped  : {skipped} (duplicate message_id)")
    return {"inserted": inserted, "skipped": skipped}
