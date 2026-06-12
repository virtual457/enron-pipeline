"""
Tests for email_composer.py, notifier_smtp.py, notifier_mcp.py, notifier.py

Covers:
- EmailComposer builds correct .eml content
- EmailComposer saves .eml file to disk
- notifier_smtp dry run generates .eml, no send
- notifier_smtp live send via mocked smtplib
- notifier_smtp missing env vars → error log entry
- notifier_smtp notify_email override used as delivery address
- notifier_mcp dry run generates .eml, no subprocess call
- notifier_mcp live send via mocked subprocess
- notifier.run_notifications dry run — all duplicates get .eml
- notifier.run_notifications marks notification_sent in DB after live send
- notifier.run_notifications skips already-notified emails
"""

import os
import sys
import sqlite3
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from email_composer import EmailComposer
from database import init_db, get_or_create_user


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

DUPLICATE = {
    "message_id": "<dup-001@enron.com>",
    "date": "2001-10-05T09:00:00+00:00",
    "subject": "Quarterly Report",
    "from_address": "sender@enron.com",
}

ORIGINAL = {
    "message_id": "<orig-001@enron.com>",
    "date": "2001-10-01T09:00:00+00:00",
    "subject": "Quarterly Report",
    "from_address": "sender@enron.com",
}

SCORE = 95.5


def seed_db(conn):
    """Insert one original + one duplicate email into DB."""
    uid = get_or_create_user(conn, "sender@enron.com", "Sender")
    conn.execute("""
        INSERT INTO emails (message_id, date, from_user_id, subject, body, source_file)
        VALUES ('<orig-001@enron.com>', '2001-10-01T09:00:00+00:00', ?, 'Quarterly Report', 'Body', 'f1')
    """, (uid,))
    conn.execute("""
        INSERT INTO emails (message_id, date, from_user_id, subject, body, source_file,
                            is_duplicate, duplicate_of, similarity_score)
        VALUES ('<dup-001@enron.com>', '2001-10-05T09:00:00+00:00', ?, 'Quarterly Report', 'Body', 'f2',
                1, '<orig-001@enron.com>', 95.5)
    """, (uid,))
    conn.commit()


# ---------------------------------------------------------------------------
# EmailComposer
# ---------------------------------------------------------------------------

class TestEmailComposer:
    def test_build_contains_required_fields(self):
        composer = EmailComposer()
        eml = composer.build(DUPLICATE, ORIGINAL, SCORE)

        assert DUPLICATE["message_id"] in eml
        assert ORIGINAL["message_id"] in eml
        assert "[Duplicate Notice]" in eml
        assert "Quarterly Report" in eml
        assert "95.5%" in eml
        assert DUPLICATE["date"] in eml
        assert ORIGINAL["date"] in eml

    def test_build_to_header_is_duplicate_sender(self):
        composer = EmailComposer()
        eml = composer.build(DUPLICATE, ORIGINAL, SCORE)
        assert "sender@enron.com" in eml

    def test_build_references_header(self):
        composer = EmailComposer()
        eml = composer.build(DUPLICATE, ORIGINAL, SCORE)
        assert "References:" in eml
        assert DUPLICATE["message_id"] in eml

    def test_save_eml_creates_file(self, tmp_path):
        composer = EmailComposer()
        eml = composer.build(DUPLICATE, ORIGINAL, SCORE)
        path = composer.save_eml(eml, str(tmp_path), DUPLICATE["message_id"])

        assert os.path.exists(path)
        assert path.endswith(".eml")
        with open(path, encoding="utf-8") as f:
            content = f.read()
        assert "[Duplicate Notice]" in content

    def test_save_eml_sanitizes_message_id(self, tmp_path):
        composer = EmailComposer()
        eml = composer.build(DUPLICATE, ORIGINAL, SCORE)
        path = composer.save_eml(eml, str(tmp_path), "<dup/001:test@enron.com>")
        # should not have < > / : in filename
        fname = os.path.basename(path)
        assert "<" not in fname
        assert ">" not in fname
        assert "/" not in fname

    def test_build_confirm_instructions_in_body(self):
        composer = EmailComposer()
        eml = composer.build(DUPLICATE, ORIGINAL, SCORE)
        assert "CONFIRM" in eml


# ---------------------------------------------------------------------------
# notifier_smtp
# ---------------------------------------------------------------------------

class TestNotifierSmtp:
    def test_dry_run_creates_eml_no_send(self, tmp_path):
        import notifier_smtp
        log = notifier_smtp.send(DUPLICATE, ORIGINAL, SCORE,
                                  output_dir=str(tmp_path), dry_run=True)
        assert log["status"] == "dry_run"
        assert os.path.exists(log["eml_path"])

    def test_dry_run_does_not_call_smtp(self, tmp_path):
        import notifier_smtp
        with patch("notifier_smtp.smtplib.SMTP") as mock_smtp:
            notifier_smtp.send(DUPLICATE, ORIGINAL, SCORE,
                                output_dir=str(tmp_path), dry_run=True)
            mock_smtp.assert_not_called()

    def test_missing_env_vars_returns_error(self, tmp_path, monkeypatch):
        import notifier_smtp
        monkeypatch.delenv("EMAIL_USER", raising=False)
        monkeypatch.delenv("EMAIL_APP_PASSWORD", raising=False)
        log = notifier_smtp.send(DUPLICATE, ORIGINAL, SCORE,
                                  output_dir=str(tmp_path), dry_run=False)
        assert log["status"] == "error"
        assert "EMAIL_USER" in log["error"] or "EMAIL_APP_PASSWORD" in log["error"]

    def test_live_send_calls_smtp_with_notify_email(self, tmp_path, monkeypatch):
        import notifier_smtp
        monkeypatch.setenv("EMAIL_USER", "me@gmail.com")
        monkeypatch.setenv("EMAIL_APP_PASSWORD", "app-pass")

        mock_server = MagicMock()
        mock_smtp_cls = MagicMock(return_value=__import__("contextlib").nullcontext(mock_server))

        with patch("notifier_smtp.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            log = notifier_smtp.send(
                DUPLICATE, ORIGINAL, SCORE,
                output_dir=str(tmp_path),
                dry_run=False,
                notify_email="chandanaws1998@gmail.com",
            )

        # sendmail called with override address
        # sendmail(from, [to_list], body) — to_list is args[1]
        call_args = mock_server.sendmail.call_args[0]
        assert "chandanaws1998@gmail.com" in call_args[1]

    def test_live_send_uses_from_address_when_no_override(self, tmp_path, monkeypatch):
        import notifier_smtp
        monkeypatch.setenv("EMAIL_USER", "me@gmail.com")
        monkeypatch.setenv("EMAIL_APP_PASSWORD", "app-pass")

        mock_server = MagicMock()
        with patch("notifier_smtp.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            notifier_smtp.send(
                DUPLICATE, ORIGINAL, SCORE,
                output_dir=str(tmp_path),
                dry_run=False,
                notify_email=None,
            )

        call_args = mock_server.sendmail.call_args[0]
        assert "sender@enron.com" in call_args[1]

    def test_smtp_exception_logged_as_error(self, tmp_path, monkeypatch):
        import notifier_smtp
        monkeypatch.setenv("EMAIL_USER", "me@gmail.com")
        monkeypatch.setenv("EMAIL_APP_PASSWORD", "app-pass")

        with patch("notifier_smtp.smtplib.SMTP", side_effect=Exception("Connection refused")):
            log = notifier_smtp.send(DUPLICATE, ORIGINAL, SCORE,
                                      output_dir=str(tmp_path), dry_run=False)

        assert log["status"] == "error"
        assert "Connection refused" in log["error"]


# ---------------------------------------------------------------------------
# notifier_mcp
# ---------------------------------------------------------------------------

class TestNotifierMcp:
    def test_dry_run_creates_eml_no_subprocess(self, tmp_path):
        import notifier_mcp
        with patch("notifier_mcp.subprocess.run") as mock_run:
            log = notifier_mcp.send(DUPLICATE, ORIGINAL, SCORE,
                                     output_dir=str(tmp_path), dry_run=True)
            mock_run.assert_not_called()
        assert log["status"] == "dry_run"
        assert os.path.exists(log["eml_path"])

    def test_live_send_calls_subprocess(self, tmp_path):
        import notifier_mcp
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stderr = ""

        with patch("notifier_mcp.subprocess.run", return_value=mock_result) as mock_run:
            log = notifier_mcp.send(DUPLICATE, ORIGINAL, SCORE,
                                     output_dir=str(tmp_path), dry_run=False,
                                     notify_email="chandanaws1998@gmail.com")
            mock_run.assert_called_once()

        assert log["status"] == "sent"
        assert log["recipient"] == "chandanaws1998@gmail.com"

    def test_live_send_subprocess_failure_logged(self, tmp_path):
        import notifier_mcp
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "MCP server not found"

        with patch("notifier_mcp.subprocess.run", return_value=mock_result):
            log = notifier_mcp.send(DUPLICATE, ORIGINAL, SCORE,
                                     output_dir=str(tmp_path), dry_run=False)

        assert log["status"] == "error"
        assert "MCP server not found" in log["error"]


# ---------------------------------------------------------------------------
# notifier.run_notifications
# ---------------------------------------------------------------------------

class TestRunNotifications:
    def test_dry_run_generates_eml_for_all_duplicates(self, tmp_path):
        from notifier import run_notifications
        conn = init_db(str(tmp_path / "test.db"))
        seed_db(conn)

        logs = run_notifications(
            conn,
            output_dir=str(tmp_path / "replies"),
            send_log_path=str(tmp_path / "send_log.csv"),
            dry_run=True,
            mode="smtp",
        )

        assert len(logs) == 1
        assert logs[0]["status"] == "dry_run"
        emls = os.listdir(str(tmp_path / "replies"))
        assert len(emls) == 1

    def test_send_log_csv_written(self, tmp_path):
        from notifier import run_notifications
        conn = init_db(str(tmp_path / "test.db"))
        seed_db(conn)

        log_path = str(tmp_path / "send_log.csv")
        run_notifications(conn, output_dir=str(tmp_path / "replies"),
                          send_log_path=log_path, dry_run=True)

        assert os.path.exists(log_path)
        with open(log_path, encoding="utf-8") as f:
            content = f.read()
        assert "timestamp" in content
        assert "status" in content

    def test_live_send_marks_notification_sent_in_db(self, tmp_path, monkeypatch):
        from notifier import run_notifications
        import notifier_smtp

        conn = init_db(str(tmp_path / "test.db"))
        seed_db(conn)

        monkeypatch.setenv("EMAIL_USER", "me@gmail.com")
        monkeypatch.setenv("EMAIL_APP_PASSWORD", "app-pass")

        mock_server = MagicMock()
        with patch("notifier_smtp.smtplib.SMTP") as mock_smtp_cls:
            mock_smtp_cls.return_value.__enter__ = MagicMock(return_value=mock_server)
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)

            run_notifications(
                conn,
                output_dir=str(tmp_path / "replies"),
                send_log_path=str(tmp_path / "send_log.csv"),
                dry_run=False,
                mode="smtp",
                notify_email="chandanaws1998@gmail.com",
            )

        row = conn.execute(
            "SELECT notification_sent, notification_date FROM emails WHERE message_id = '<dup-001@enron.com>'"
        ).fetchone()
        assert row["notification_sent"] == 1
        assert row["notification_date"] is not None

    def test_already_notified_emails_skipped(self, tmp_path):
        from notifier import run_notifications
        conn = init_db(str(tmp_path / "test.db"))
        seed_db(conn)

        # Mark already notified
        conn.execute(
            "UPDATE emails SET notification_sent=1 WHERE message_id='<dup-001@enron.com>'"
        )
        conn.commit()

        logs = run_notifications(
            conn,
            output_dir=str(tmp_path / "replies"),
            send_log_path=str(tmp_path / "send_log.csv"),
            dry_run=True,
        )
        assert logs == []

    def test_no_duplicates_returns_empty(self, tmp_path):
        from notifier import run_notifications
        conn = init_db(str(tmp_path / "test.db"))
        # empty DB — no duplicates
        logs = run_notifications(
            conn,
            output_dir=str(tmp_path / "replies"),
            send_log_path=str(tmp_path / "send_log.csv"),
            dry_run=True,
        )
        assert logs == []
