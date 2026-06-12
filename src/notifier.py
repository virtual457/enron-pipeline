import csv
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def run_notifications(
    conn,
    output_dir: str = "output/replies",
    send_log_path: str = "output/send_log.csv",
    dry_run: bool = True,
    mode: str = "smtp",
    notify_email: str | None = None,
    max_notifications: int | None = None,
) -> list[dict]:
    """
    Generate .eml files for all flagged duplicates.
    Optionally send live notifications.

    mode: 'smtp' (default) or 'mcp'
    dry_run: if True, only generates .eml files, does not send
    """
    if mode == "mcp":
        from notifier_mcp import send
    else:
        from notifier_smtp import send

    # Fetch all flagged duplicates with their originals
    rows = conn.execute(
        """
        SELECT
            d.message_id        AS dup_id,
            d.date              AS dup_date,
            d.subject           AS subject,
            d.similarity_score  AS score,
            ud.email            AS dup_from,
            o.message_id        AS orig_id,
            o.date              AS orig_date,
            uo.email            AS orig_from
        FROM emails d
        JOIN users ud ON d.from_user_id = ud.user_id
        JOIN emails o  ON d.duplicate_of = o.message_id
        JOIN users uo  ON o.from_user_id = uo.user_id
        WHERE d.is_duplicate = 1
          AND d.notification_sent = 0
        ORDER BY d.date
        """
    ).fetchall()

    if not rows:
        print("No pending notifications.")
        return []

    if max_notifications:
        rows = rows[:max_notifications]

    print(f"Sending notifications for {len(rows)} duplicates (mode={mode}, dry_run={dry_run})")

    logs = []
    sent = 0
    errors = 0

    for row in rows:
        duplicate = {
            "message_id": row["dup_id"],
            "date": row["dup_date"],
            "subject": row["subject"],
            "from_address": row["dup_from"],
        }
        original = {
            "message_id": row["orig_id"],
            "date": row["orig_date"],
            "from_address": row["orig_from"],
        }
        score = row["score"] or 0.0

        log_entry = send(duplicate, original, score, output_dir=output_dir,
                         dry_run=dry_run, notify_email=notify_email)
        log_entry["timestamp"] = datetime.now(timezone.utc).isoformat()
        logs.append(log_entry)

        if log_entry["status"] == "sent":
            sent += 1
            # Mark notification sent in DB
            conn.execute(
                """
                UPDATE emails
                SET notification_sent = 1, notification_date = ?
                WHERE message_id = ?
                """,
                (log_entry["timestamp"], duplicate["message_id"]),
            )
        elif log_entry["status"] == "error":
            errors += 1

    conn.commit()
    _write_send_log(logs, send_log_path)

    print(f"\n=== Notification Stats ===")
    print(f"Total     : {len(rows)}")
    print(f"Sent      : {sent}")
    print(f"Dry run   : {len(rows) - sent - errors}")
    print(f"Errors    : {errors}")
    print(f"Log written: {send_log_path}")

    return logs


def _write_send_log(logs: list[dict], path: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fields = ["timestamp", "mode", "recipient", "subject", "eml_path", "status", "error"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(logs)
