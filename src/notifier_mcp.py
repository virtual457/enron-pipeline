import logging
import subprocess
import json

from email_composer import EmailComposer

logger = logging.getLogger(__name__)


def send(duplicate: dict, original: dict, score: float,
         output_dir: str = "output/replies", dry_run: bool = True,
         notify_email: str | None = None) -> dict:
    """
    Generate .eml draft and optionally send via Gmail MCP server.

    MCP server must be configured in .claude/mcp.json.
    Uses the 'send_email' MCP tool via Claude Code CLI.

    Returns a log entry dict.
    """
    composer = EmailComposer()
    eml_content = composer.build(duplicate, original, score)
    eml_path = composer.save_eml(eml_content, output_dir, duplicate["message_id"])

    subject = f"[Duplicate Notice] Re: {duplicate.get('subject', '')}"
    to_addr = notify_email or duplicate.get("from_address", "")

    log_entry = {
        "mode": "mcp",
        "recipient": to_addr,
        "subject": subject,
        "eml_path": eml_path,
        "status": "dry_run",
        "error": "",
    }

    if dry_run:
        logger.info("Dry run (MCP) — .eml saved: %s", eml_path)
        return log_entry

    # Extract plain text body from eml
    body_start = eml_content.find("\n\n")
    body = eml_content[body_start:].strip() if body_start != -1 else eml_content

    tool_call = {
        "tool": "send_email",
        "parameters": {
            "to": to_addr,
            "subject": subject,
            "body": body,
        },
    }

    try:
        result = subprocess.run(
            ["claude", "mcp", "call", json.dumps(tool_call)],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            log_entry["status"] = "sent"
            logger.info("Sent via MCP to %s", to_addr)
        else:
            log_entry["status"] = "error"
            log_entry["error"] = result.stderr.strip()
            logger.error("MCP send failed: %s", result.stderr)
    except Exception as e:
        log_entry["status"] = "error"
        log_entry["error"] = str(e)
        logger.error("MCP send error: %s", e)

    return log_entry
