import logging
import os
import smtplib
from email.parser import Parser

from dotenv import load_dotenv

from email_composer import EmailComposer

load_dotenv()

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send(duplicate: dict, original: dict, score: float,
         output_dir: str = "output/replies", dry_run: bool = True,
         notify_email: str | None = None) -> dict:
    """
    Generate .eml draft and optionally send via Gmail SMTP.

    Requires env vars when dry_run=False:
        EMAIL_USER         Gmail address
        EMAIL_APP_PASSWORD Gmail app password (not account password)

    Returns a log entry dict.
    """
    composer = EmailComposer()
    eml_content = composer.build(duplicate, original, score)
    eml_path = composer.save_eml(eml_content, output_dir, duplicate["message_id"])

    log_entry = {
        "mode": "smtp",
        "recipient": duplicate.get("from_address", ""),
        "subject": f"[Duplicate Notice] Re: {duplicate.get('subject', '')}",
        "eml_path": eml_path,
        "status": "dry_run",
        "error": "",
    }

    if dry_run:
        logger.info("Dry run — .eml saved: %s", eml_path)
        return log_entry

    user = os.environ.get("EMAIL_USER")
    password = os.environ.get("EMAIL_APP_PASSWORD")
    if not user or not password:
        log_entry["status"] = "error"
        log_entry["error"] = "EMAIL_USER or EMAIL_APP_PASSWORD not set"
        logger.error(log_entry["error"])
        return log_entry

    try:
        # notify_email overrides the Enron address (which would bounce)
        to_addr = notify_email or duplicate.get("from_address", "")

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, [to_addr], eml_content)

        log_entry["status"] = "sent"
        logger.info("Sent via SMTP to %s", to_addr)
    except Exception as e:
        log_entry["status"] = "error"
        log_entry["error"] = str(e)
        logger.error("SMTP send failed: %s", e)

    return log_entry
