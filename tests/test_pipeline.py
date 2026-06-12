"""
Integration tests for the extract + insert pipeline.
Tests the full loop: iter_files → parse_email → insert_email
"""

import os
import sys
import textwrap
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from extractor import iter_files, parse_email
from database import init_db, insert_email, get_or_create_user

REAL_MAILDIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "data", "maildir"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_email_file(directory: str, filename: str, **kwargs) -> str:
    """Write a minimal valid raw email file."""
    msg_id = kwargs.get("message_id", f"<{uuid.uuid4()}@test.com>")
    from_addr = kwargs.get("from_addr", "sender@enron.com")
    to_addr = kwargs.get("to_addr", "recipient@enron.com")
    cc_addr = kwargs.get("cc_addr", "")
    bcc_addr = kwargs.get("bcc_addr", "")
    subject = kwargs.get("subject", "Test Subject")
    body = kwargs.get("body", "Test body content.")

    lines = [
        f"Message-ID: {msg_id}",
        "Date: Mon, 1 Oct 2001 09:00:00 +0000",
        f"From: {from_addr}",
        f"To: {to_addr}",
    ]
    if cc_addr:
        lines.append(f"Cc: {cc_addr}")
    if bcc_addr:
        lines.append(f"Bcc: {bcc_addr}")
    lines += [
        f"Subject: {subject}",
        "Mime-Version: 1.0",
        "Content-Type: text/plain; charset=us-ascii",
        "",
        body,
    ]
    content = "\n".join(lines) + "\n"
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def make_synthetic_maildir(base: str, mailboxes: dict) -> str:
    """
    Create a synthetic maildir structure.
    mailboxes: {mailbox_name: num_emails}
    Returns path to maildir root.
    """
    maildir = os.path.join(base, "maildir")
    for mb_name, count in mailboxes.items():
        mb_path = os.path.join(maildir, mb_name, "inbox")
        os.makedirs(mb_path, exist_ok=True)
        for i in range(count):
            make_email_file(
                mb_path,
                str(i),
                message_id=f"<{mb_name}-{i}@test.com>",
                subject=f"Email {i} from {mb_name}",
            )
    return maildir


# ---------------------------------------------------------------------------
# Test 1: Full pipeline stops at min criteria
# ---------------------------------------------------------------------------

class TestFullPipelineMinCriteria:
    def test_stops_at_min_mailboxes_and_emails(self, tmp_path):
        maildir = make_synthetic_maildir(str(tmp_path), {"mb1": 30, "mb2": 30, "mb3": 30})
        conn = init_db(str(tmp_path / "test.db"))

        processed_mb = set()
        inserted = 0
        MIN_MB = 2
        MIN_EMAILS = 50

        for mailbox, filepath in iter_files(maildir, ["mb1", "mb2", "mb3"]):
            try:
                record = parse_email(filepath, maildir)
                if insert_email(conn, record):
                    inserted += 1
                    processed_mb.add(mailbox)
            except Exception:
                pass
            if len(processed_mb) >= MIN_MB and inserted >= MIN_EMAILS:
                break

        conn.commit()
        assert len(processed_mb) >= MIN_MB
        assert inserted >= MIN_EMAILS
        # should NOT have processed all 90 files
        assert inserted < 90


# ---------------------------------------------------------------------------
# Test 2: Inserted email fields correct
# ---------------------------------------------------------------------------

class TestInsertedEmailFields:
    def test_mandatory_fields_in_db(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        mb_path = os.path.join(maildir, "mb1")
        os.makedirs(mb_path)
        make_email_file(
            mb_path, "msg1",
            message_id="<field-test-001@enron.com>",
            from_addr="alice@enron.com",
            to_addr="bob@enron.com",
            subject="Field Test Email",
            body="This is the body.",
        )

        conn = init_db(str(tmp_path / "test.db"))
        for _, filepath in iter_files(maildir, ["mb1"]):
            record = parse_email(filepath, maildir)
            insert_email(conn, record)
        conn.commit()

        row = conn.execute(
            "SELECT e.message_id, e.date, e.subject, u.email "
            "FROM emails e JOIN users u ON e.from_user_id = u.user_id"
        ).fetchone()
        assert row["message_id"] == "<field-test-001@enron.com>"
        assert row["date"].endswith("+00:00")
        assert row["subject"] == "Field Test Email"
        assert row["email"] == "alice@enron.com"


# ---------------------------------------------------------------------------
# Test 3: Users table populated
# ---------------------------------------------------------------------------

class TestUsersTablePopulated:
    def test_from_and_to_in_users(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        mb_path = os.path.join(maildir, "mb1")
        os.makedirs(mb_path)
        make_email_file(
            mb_path, "msg1",
            from_addr="sender@enron.com",
            to_addr="receiver@enron.com",
        )

        conn = init_db(str(tmp_path / "test.db"))
        for _, filepath in iter_files(maildir, ["mb1"]):
            record = parse_email(filepath, maildir)
            insert_email(conn, record)
        conn.commit()

        emails_in_users = [
            r[0] for r in conn.execute("SELECT email FROM users").fetchall()
        ]
        assert "sender@enron.com" in emails_in_users
        assert "receiver@enron.com" in emails_in_users


# ---------------------------------------------------------------------------
# Test 4: email_recipients table populated
# ---------------------------------------------------------------------------

class TestEmailRecipientsPopulated:
    def test_to_cc_bcc_in_recipients(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        mb_path = os.path.join(maildir, "mb1")
        os.makedirs(mb_path)
        make_email_file(
            mb_path, "msg1",
            message_id="<recip-test@enron.com>",
            from_addr="sender@enron.com",
            to_addr="to@enron.com",
            cc_addr="cc@enron.com",
            bcc_addr="bcc@enron.com",
        )

        conn = init_db(str(tmp_path / "test.db"))
        for _, filepath in iter_files(maildir, ["mb1"]):
            record = parse_email(filepath, maildir)
            insert_email(conn, record)
        conn.commit()

        rows = conn.execute(
            "SELECT u.email, r.type FROM email_recipients r "
            "JOIN users u ON r.user_id = u.user_id "
            "WHERE r.message_id = '<recip-test@enron.com>'"
        ).fetchall()
        types = {r["email"]: r["type"] for r in rows}
        assert types.get("to@enron.com") == "to"
        assert types.get("cc@enron.com") == "cc"
        assert types.get("bcc@enron.com") == "bcc"


# ---------------------------------------------------------------------------
# Test 5: Duplicate message_id skipped
# ---------------------------------------------------------------------------

class TestDuplicateMessageIdSkipped:
    def test_second_insert_skipped(self, tmp_path):
        conn = init_db(str(tmp_path / "test.db"))
        record = {
            "message_id": "<dup-test@enron.com>",
            "date": "2001-10-01T09:00:00+00:00",
            "from_address": "sender@enron.com",
            "to_addresses": ["recipient@enron.com"],
            "cc_addresses": [],
            "bcc_addresses": [],
            "subject": "Duplicate test",
            "body": "Body content.",
            "source_file": "maildir/mb1/1",
            "x_from": None, "x_to": None, "x_cc": None, "x_bcc": None,
            "x_folder": None, "x_origin": None, "content_type": None,
            "has_attachment": False, "forwarded_content": None,
            "quoted_content": None, "headings": None,
        }
        first = insert_email(conn, record)
        second = insert_email(conn, record)
        conn.commit()

        assert first is True
        assert second is False
        count = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        assert count == 1


# ---------------------------------------------------------------------------
# Test 6: Error log for unparseable files
# ---------------------------------------------------------------------------

class TestErrorLog:
    def test_missing_message_id_logged(self, tmp_path):
        bad_file = str(tmp_path / "bad_email")
        with open(bad_file, "w") as f:
            f.write("Date: Mon, 1 Oct 2001 09:00:00 +0000\nFrom: x@y.com\n\nBody.\n")

        error_log = str(tmp_path / "errors.log")
        errors = []
        try:
            parse_email(bad_file, str(tmp_path))
        except Exception as e:
            errors.append({"file": bad_file, "reason": str(e)})

        with open(error_log, "w", encoding="utf-8") as f:
            for err in errors:
                f.write(f"{err['file']}\t{err['reason']}\n")

        with open(error_log, encoding="utf-8") as f:
            content = f.read()
        assert "bad_email" in content
        assert "Message-ID" in content


# ---------------------------------------------------------------------------
# Test 7: Smoke test with real allen-p data
# ---------------------------------------------------------------------------

class TestSmokeAllenP:
    @pytest.mark.skipif(
        not os.path.exists(os.path.join(REAL_MAILDIR, "allen-p")),
        reason="Real maildir not present",
    )
    def test_insert_100_real_emails(self, tmp_path):
        conn = init_db(str(tmp_path / "smoke.db"))
        inserted = 0
        errors = 0

        for _, filepath in iter_files(REAL_MAILDIR, ["allen-p"]):
            try:
                record = parse_email(filepath, REAL_MAILDIR)
                if insert_email(conn, record):
                    inserted += 1
            except Exception:
                errors += 1
            if inserted >= 100:
                break

        conn.commit()
        assert inserted == 100

        email_count = conn.execute("SELECT COUNT(*) FROM emails").fetchone()[0]
        user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        recip_count = conn.execute("SELECT COUNT(*) FROM email_recipients").fetchone()[0]

        assert email_count == 100
        assert user_count > 0
        assert recip_count > 0
        print(f"\nSmoke: {email_count} emails, {user_count} users, {recip_count} recipients")
