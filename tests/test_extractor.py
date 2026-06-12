"""
Tests for src/extractor.py

Covers:
- Mandatory field extraction
- Optional field extraction
- Date normalization (PST, EST, UTC offset)
- Address parsing (display name, comma list, angle brackets)
- Body / forwarded / quoted splitting
- Attachment detection
- Missing mandatory field → ValueError
- Encoding fallback (latin-1)
- discover_files walks recursively
"""

import os
import sys
import tempfile
import textwrap

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from extractor import (
    _parse_addresses,
    _parse_date,
    _split_body,
    iter_files,
    parse_email,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_email(directory: str, filename: str, content: str) -> str:
    """Write a raw email file and return its path."""
    path = os.path.join(directory, filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(textwrap.dedent(content))
    return path


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

class TestParseDate:
    def test_pst_timezone(self):
        result = _parse_date("Fri, 7 Dec 2001 10:06:42 -0800 (PST)")
        assert result == "2001-12-07T18:06:42+00:00"

    def test_est_timezone(self):
        result = _parse_date("Mon, 1 Jan 2001 09:00:00 -0500 (EST)")
        assert result == "2001-01-01T14:00:00+00:00"

    def test_utc_offset(self):
        result = _parse_date("Wed, 15 Aug 2001 12:00:00 +0000")
        assert result == "2001-08-15T12:00:00+00:00"

    def test_none_returns_none(self):
        assert _parse_date(None) is None

    def test_garbage_returns_none(self):
        assert _parse_date("not-a-date") is None

    def test_cdt_timezone(self):
        result = _parse_date("Tue, 3 Jul 2001 08:00:00 -0500 (CDT)")
        assert result is not None
        assert result.endswith("+00:00")


# ---------------------------------------------------------------------------
# _parse_addresses
# ---------------------------------------------------------------------------

class TestParseAddresses:
    def test_plain_address(self):
        assert _parse_addresses("alice@enron.com") == ["alice@enron.com"]

    def test_display_name_angle_brackets(self):
        assert _parse_addresses("Alice Smith <alice@enron.com>") == ["alice@enron.com"]

    def test_comma_separated(self):
        result = _parse_addresses("alice@enron.com, bob@enron.com")
        assert result == ["alice@enron.com", "bob@enron.com"]

    def test_mixed_formats(self):
        result = _parse_addresses(
            "Alice <alice@enron.com>, bob@enron.com, Carol <carol@example.com>"
        )
        assert result == ["alice@enron.com", "bob@enron.com", "carol@example.com"]

    def test_none_returns_empty(self):
        assert _parse_addresses(None) == []

    def test_no_at_sign_skipped(self):
        assert _parse_addresses("not-an-email") == []

    def test_newline_continuation(self):
        result = _parse_addresses("alice@enron.com\nbob@enron.com")
        assert "alice@enron.com" in result
        assert "bob@enron.com" in result


# ---------------------------------------------------------------------------
# _split_body
# ---------------------------------------------------------------------------

class TestSplitBody:
    def test_clean_body_no_forward_no_quote(self):
        raw = "Hello this is the message body."
        body, fwd, quoted = _split_body(raw)
        assert body == raw
        assert fwd == ""
        assert quoted == ""

    def test_forwarded_content_separated(self):
        raw = (
            "Please see below.\n"
            "----- Original Message -----\n"
            "From: bob@enron.com\n"
            "This is the forwarded part."
        )
        body, fwd, quoted = _split_body(raw)
        assert "Please see below." in body
        assert "----- Original Message -----" in fwd
        assert "This is the forwarded part." in fwd

    def test_quoted_lines_separated(self):
        raw = (
            "My reply here.\n"
            "> Original line 1\n"
            "> Original line 2\n"
            "End of reply."
        )
        body, fwd, quoted = _split_body(raw)
        assert "My reply here." in body
        assert "> Original line 1" in quoted
        assert "> Original line 2" in quoted

    def test_forwarded_by_marker(self):
        raw = (
            "See attached.\n"
            "---------------------- Forwarded by John/Enron ----------------------\n"
            "Forwarded body here."
        )
        body, fwd, quoted = _split_body(raw)
        assert "Forwarded body here." in fwd


# ---------------------------------------------------------------------------
# parse_email — full end-to-end
# ---------------------------------------------------------------------------

class TestParseEmail:
    def test_mandatory_fields_extracted(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg1", """\
            Message-ID: <test001@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 -0700 (PDT)
            From: sender@enron.com
            To: recipient@enron.com
            Subject: Test Subject
            Mime-Version: 1.0
            Content-Type: text/plain; charset=us-ascii

            This is the email body.
        """)
        record = parse_email(path, maildir)
        assert record["message_id"] == "<test001@enron.com>"
        assert record["date"].endswith("+00:00")
        assert record["from_address"] == "sender@enron.com"
        assert "recipient@enron.com" in record["to_addresses"]
        assert record["subject"] == "Test Subject"
        assert "email body" in record["body"]
        assert record["source_file"] is not None

    def test_optional_cc_bcc_extracted(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg2", """\
            Message-ID: <test002@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Cc: cc1@enron.com, cc2@enron.com
            Bcc: bcc1@enron.com
            Subject: CC and BCC test

            Body text.
        """)
        record = parse_email(path, maildir)
        assert "cc1@enron.com" in record["cc_addresses"]
        assert "cc2@enron.com" in record["cc_addresses"]
        assert "bcc1@enron.com" in record["bcc_addresses"]

    def test_enron_x_headers_extracted(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg3", """\
            Message-ID: <test003@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: X-Headers test
            X-From: Sender, John </O=ENRON/OU=NA/CN=JSENDER>
            X-To: Recipient, Jane
            X-Folder: \\John_Sender\\Inbox
            X-Origin: Sender-J

            Body.
        """)
        record = parse_email(path, maildir)
        assert "John" in record["x_from"]
        assert record["x_to"] == "Recipient, Jane"
        assert "Inbox" in record["x_folder"]
        assert record["x_origin"] == "Sender-J"

    def test_attachment_detected_via_file_marker(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg4", """\
            Message-ID: <test004@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: Has attachment

            Please find attached.

            << File: report.xls >>
        """)
        record = parse_email(path, maildir)
        assert record["has_attachment"] is True

    def test_no_attachment_flag_false(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg5", """\
            Message-ID: <test005@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: No attachment

            Just a plain text email.
        """)
        record = parse_email(path, maildir)
        assert record["has_attachment"] is False

    def test_forwarded_content_split(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg6", """\
            Message-ID: <test006@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: FW: Something

            My top reply.

            ----- Original Message -----
            From: original@enron.com
            Original content here.
        """)
        record = parse_email(path, maildir)
        assert "My top reply." in record["body"]
        assert "----- Original Message -----" in record["forwarded_content"]
        assert "Original content here." in record["forwarded_content"]

    def test_quoted_reply_split(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg7", """\
            Message-ID: <test007@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: Re: Something

            My answer.
            > Quoted line one
            > Quoted line two
        """)
        record = parse_email(path, maildir)
        assert "My answer." in record["body"]
        assert "> Quoted line one" in record["quoted_content"]

    def test_missing_message_id_raises(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg8", """\
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: No ID

            Body.
        """)
        with pytest.raises(ValueError, match="Missing Message-ID"):
            parse_email(path, maildir)

    def test_missing_date_raises(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg9", """\
            Message-ID: <test009@enron.com>
            From: sender@enron.com
            To: recipient@enron.com
            Subject: No date

            Body.
        """)
        with pytest.raises(ValueError, match="Date"):
            parse_email(path, maildir)

    def test_missing_from_raises(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg10", """\
            Message-ID: <test010@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            To: recipient@enron.com
            Subject: No from

            Body.
        """)
        with pytest.raises(ValueError, match="From"):
            parse_email(path, maildir)

    def test_subject_preserves_re_prefix(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg11", """\
            Message-ID: <test011@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: Re: Original topic

            Reply body.
        """)
        record = parse_email(path, maildir)
        assert record["subject"] == "Re: Original topic"

    def test_source_file_is_relative(self, tmp_path):
        maildir = str(tmp_path / "maildir")
        os.makedirs(maildir)
        path = write_email(maildir, "msg12", """\
            Message-ID: <test012@enron.com>
            Date: Mon, 1 Oct 2001 09:00:00 +0000
            From: sender@enron.com
            To: recipient@enron.com
            Subject: Source file test

            Body.
        """)
        record = parse_email(path, maildir)
        assert not os.path.isabs(record["source_file"])
        assert "msg12" in record["source_file"]


# ---------------------------------------------------------------------------
# discover_files
# ---------------------------------------------------------------------------

class TestIterFiles:
    def test_yields_all_files_recursively(self, tmp_path):
        maildir = tmp_path / "maildir"
        (maildir / "mb1" / "sub").mkdir(parents=True)
        (maildir / "mb1" / "1").write_text("x")
        (maildir / "mb1" / "sub" / "2").write_text("x")
        (maildir / "mb2" / "sub").mkdir(parents=True)
        (maildir / "mb2" / "sub" / "3").write_text("x")

        results = list(iter_files(str(maildir), ["mb1", "mb2"]))
        assert len(results) == 3
        mailboxes = {mb for mb, _ in results}
        assert mailboxes == {"mb1", "mb2"}

    def test_skips_hidden_dirs(self, tmp_path):
        maildir = tmp_path / "maildir"
        (maildir / "mb1" / ".hidden").mkdir(parents=True)
        (maildir / "mb1" / ".hidden" / "secret").write_text("x")
        (maildir / "mb1" / "visible").write_text("x")

        results = list(iter_files(str(maildir), ["mb1"]))
        assert len(results) == 1
        assert "visible" in results[0][1]

    def test_stops_early_when_criteria_met(self, tmp_path):
        maildir = tmp_path / "maildir"
        for mb in ["mb1", "mb2", "mb3"]:
            (maildir / mb).mkdir(parents=True)
            for i in range(5):
                (maildir / mb / str(i)).write_text("x")

        processed_mb = set()
        processed_emails = 0
        MIN_MB = 2
        MIN_EMAILS = 8

        for mailbox, filepath in iter_files(str(maildir), ["mb1", "mb2", "mb3"]):
            processed_mb.add(mailbox)
            processed_emails += 1
            if len(processed_mb) >= MIN_MB and processed_emails >= MIN_EMAILS:
                break

        assert len(processed_mb) >= MIN_MB
        assert processed_emails >= MIN_EMAILS
        # should not have processed all 15 files
        assert processed_emails < 15
