import os
import email
import logging
import re
from datetime import timezone

from dateutil import parser as dateparser
from dateutil.tz import gettz

logger = logging.getLogger(__name__)

# Timezone abbreviation map for dateutil fallback
TZ_MAP = {
    "PST": gettz("America/Los_Angeles"),
    "PDT": gettz("America/Los_Angeles"),
    "MST": gettz("America/Denver"),
    "MDT": gettz("America/Denver"),
    "CST": gettz("America/Chicago"),
    "CDT": gettz("America/Chicago"),
    "EST": gettz("America/New_York"),
    "EDT": gettz("America/New_York"),
}

FORWARD_MARKERS = re.compile(
    r"(-{3,}\s*(Original Message|Forwarded by\b.*|Forwarded Message)\s*-{3,})",
    re.IGNORECASE,
)
SUBJECT_PREFIX = re.compile(r"^(re|fwd?|fw)\s*:\s*", re.IGNORECASE)


def _win_path(path: str) -> str:
    """Prepend \\?\\ prefix so Windows can open trailing-dot filenames.
    Cannot use os.path.abspath — it strips trailing dots on Windows.
    """
    path = path.replace("/", "\\")
    if not os.path.isabs(path):
        path = os.getcwd() + "\\" + path
    # Normalize separators but preserve trailing dot
    parts = path.split("\\")
    normalized = "\\".join(p for p in parts if p not in (".", ""))
    if not normalized.startswith("\\\\?\\"):
        normalized = "\\\\?\\" + normalized
    return normalized


def sorted_mailboxes(maildir_path: str) -> list[str]:
    """Return mailbox names sorted by email count descending."""
    entries = []
    for name in os.listdir(maildir_path):
        full = os.path.join(maildir_path, name)
        if os.path.isdir(full) and not name.startswith("."):
            count = sum(len(fs) for _, _, fs in os.walk(full))
            entries.append((name, count))
    entries.sort(key=lambda x: x[1])
    return [name for name, _ in entries]


def iter_files(maildir_path: str, mailboxes: list[str]):
    """Generator — yields (mailbox_name, filepath) one at a time."""
    for mailbox in mailboxes:
        mailbox_path = os.path.join(maildir_path, mailbox)
        for root, dirs, files in os.walk(mailbox_path):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            for fname in files:
                yield mailbox, os.path.join(root, fname)


def _read_file(filepath: str) -> str | None:
    win = _win_path(filepath)
    for enc in ("utf-8", "latin-1", "cp1252"):
        try:
            with open(win, encoding=enc, errors="replace") as f:
                return f.read()
        except Exception:
            continue
    return None


def _parse_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    try:
        dt = dateparser.parse(date_str, tzinfos=TZ_MAP)
        if dt is None:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


def _parse_addresses(header_val: str | None) -> list[str]:
    if not header_val:
        return []
    addrs = []
    for part in re.split(r"[,\n]", header_val):
        part = part.strip()
        # Extract address from "Display Name <addr>" or plain addr
        m = re.search(r"<([^>]+)>", part)
        addr = m.group(1).strip() if m else part
        addr = addr.strip().lower()
        if "@" in addr:
            addrs.append(addr)
    return addrs


def _split_body(raw_body: str) -> tuple[str, str, str]:
    """Return (body, forwarded_content, quoted_content)."""
    lines = raw_body.splitlines()
    body_lines, forwarded_lines, quoted_lines = [], [], []
    in_forward = False

    for line in lines:
        if FORWARD_MARKERS.search(line):
            in_forward = True
        if in_forward:
            forwarded_lines.append(line)
        elif line.startswith(">"):
            quoted_lines.append(line)
        else:
            body_lines.append(line)

    return (
        "\n".join(body_lines).strip(),
        "\n".join(forwarded_lines).strip(),
        "\n".join(quoted_lines).strip(),
    )


def _has_attachment(msg) -> bool:
    ct = msg.get_content_type() or ""
    if "multipart" in ct:
        for part in msg.walk():
            if part.get_content_disposition() in ("attachment", "inline"):
                return True
    # Check body text for attachment references
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    body += part.get_payload(decode=True).decode("latin-1", errors="replace")
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True) or b""
            body = body.decode("latin-1", errors="replace")
        except Exception:
            body = str(msg.get_payload())
    return bool(re.search(r"<<\s*File:", body, re.IGNORECASE))


def _extract_body_text(msg) -> str:
    if msg.is_multipart():
        parts = []
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                try:
                    parts.append(
                        part.get_payload(decode=True).decode("latin-1", errors="replace")
                    )
                except Exception:
                    pass
        return "\n".join(parts)
    else:
        try:
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode("latin-1", errors="replace")
        except Exception:
            pass
        return str(msg.get_payload() or "")


def _relative_path(filepath: str, maildir_path: str) -> str:
    try:
        return os.path.relpath(filepath, os.path.dirname(maildir_path)).replace("\\", "/")
    except ValueError:
        return filepath


def parse_email(filepath: str, maildir_path: str) -> dict | None:
    """Parse a single email file. Returns dict or raises ValueError."""
    raw = _read_file(filepath)
    if raw is None:
        raise ValueError("Could not read file (encoding issue)")

    msg = email.message_from_string(raw)

    # --- Mandatory fields ---
    message_id = msg.get("Message-ID", "").strip()
    if not message_id:
        raise ValueError("Missing Message-ID")

    date_str = _parse_date(msg.get("Date"))
    if not date_str:
        raise ValueError("Missing or unparseable Date")

    from_raw = msg.get("From", "")
    from_addrs = _parse_addresses(from_raw)
    if not from_addrs:
        raise ValueError("Missing From address")
    from_address = from_addrs[0]

    to_addresses = _parse_addresses(msg.get("To", ""))
    subject = (msg.get("Subject") or "").strip()

    raw_body = _extract_body_text(msg)
    body, forwarded_content, quoted_content = _split_body(raw_body)

    source_file = _relative_path(filepath, maildir_path)

    # --- Optional fields ---
    cc_addresses = _parse_addresses(msg.get("Cc", ""))
    bcc_addresses = _parse_addresses(msg.get("Bcc", ""))
    x_from = (msg.get("X-From") or "").strip()
    x_to = (msg.get("X-To") or "").strip()
    x_cc = (msg.get("X-cc") or "").strip()
    x_bcc = (msg.get("X-bcc") or "").strip()
    x_folder = (msg.get("X-Folder") or "").strip()
    x_origin = (msg.get("X-Origin") or "").strip()
    content_type = (msg.get("Content-Type") or "").strip()
    has_attachment = _has_attachment(msg)

    # Extract headings: lines that look like a title (short, no punctuation, possibly ALL CAPS)
    heading_lines = [
        line.strip()
        for line in raw_body.splitlines()
        if re.match(r"^[A-Z][A-Z\s\d\-/]{3,60}$", line.strip())
    ]
    headings = "\n".join(heading_lines) if heading_lines else None

    return {
        "message_id": message_id,
        "date": date_str,
        "from_address": from_address,
        "to_addresses": to_addresses,
        "subject": subject,
        "body": body,
        "source_file": source_file,
        "cc_addresses": cc_addresses,
        "bcc_addresses": bcc_addresses,
        "x_from": x_from or None,
        "x_to": x_to or None,
        "x_cc": x_cc or None,
        "x_bcc": x_bcc or None,
        "x_folder": x_folder or None,
        "x_origin": x_origin or None,
        "content_type": content_type or None,
        "has_attachment": has_attachment,
        "forwarded_content": forwarded_content or None,
        "quoted_content": quoted_content or None,
        "headings": headings,
    }


