"""
Enron Email Pipeline
Usage:
    python main.py --task all --maildir data/maildir
    python main.py --task 4 --send-live --notify-email you@gmail.com --notifier smtp
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from database import init_db, insert_email, get_connection
from duplicates import detect_duplicates, write_report
from extractor import sorted_mailboxes, iter_files, parse_email
from notifier import run_notifications

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

DEFAULT_MIN_MAILBOXES = 5
DEFAULT_MIN_EMAILS = 10_000
DEFAULT_DB = "enron.db"
DEFAULT_MAILDIR = "data/maildir"
DEFAULT_ERROR_LOG = "error_log.txt"
DEFAULT_REPORT = "output/duplicates_report.csv"
DEFAULT_OUTPUT_DIR = "output/replies"
DEFAULT_SEND_LOG = "output/send_log.csv"


def task_extract_store(args):
    """Task 1 + 2: extract emails and store in DB."""
    maildir = args.maildir
    db_path = args.db
    min_mb = args.min_mailboxes
    min_emails = args.min_emails

    if not os.path.isdir(maildir):
        print(f"ERROR: maildir not found: {maildir}")
        sys.exit(1)

    conn = init_db(db_path)

    # Get mailboxes sorted by size descending
    if args.mailboxes:
        mb_list = args.mailboxes
        print(f"Using specified mailboxes: {mb_list}")
    else:
        mb_list = sorted_mailboxes(maildir)
        print(f"Found {len(mb_list)} mailboxes, sorted by size descending")

    print(f"Criteria: >= {min_mb} mailboxes AND >= {min_emails} emails")
    print(f"DB: {db_path}\n")

    processed_mb = set()
    inserted = 0
    failed = 0
    error_lines = []

    for mailbox, filepath in iter_files(maildir, mb_list):
        try:
            record = parse_email(filepath, maildir)
            if insert_email(conn, record):
                inserted += 1
                processed_mb.add(mailbox)
        except Exception as e:
            failed += 1
            error_lines.append(f"{filepath}\t{e}")

        total = inserted + failed
        if total % 1000 == 0 and total > 0:
            conn.commit()
            print(f"  {total} processed | {inserted} inserted | {failed} failed "
                  f"| mailboxes: {len(processed_mb)}", flush=True)

        if len(processed_mb) >= min_mb and inserted >= min_emails:
            break

    conn.commit()

    # Write error log
    os.makedirs(os.path.dirname(os.path.abspath(DEFAULT_ERROR_LOG)), exist_ok=True)
    with open(DEFAULT_ERROR_LOG, "w", encoding="utf-8") as f:
        f.write("\n".join(error_lines))

    print(f"\n=== Extraction & Storage Stats ===")
    print(f"Mailboxes processed : {len(processed_mb)}")
    print(f"Emails inserted     : {inserted}")
    print(f"Failed parses       : {failed}")
    print(f"Error log           : {DEFAULT_ERROR_LOG}")

    conn.close()


def task_duplicates(args):
    """Task 3: detect duplicates and write report."""
    conn = get_connection(args.db)
    flagged = detect_duplicates(conn)
    if flagged:
        write_report(flagged, DEFAULT_REPORT)
    else:
        print("No duplicates found.")
    conn.close()


def task_notify(args):
    """Task 4: generate .eml files and optionally send live."""
    dry_run = not args.send_live
    conn = get_connection(args.db)
    run_notifications(
        conn,
        output_dir=DEFAULT_OUTPUT_DIR,
        send_log_path=DEFAULT_SEND_LOG,
        dry_run=dry_run,
        mode=args.notifier,
        notify_email=args.notify_email,
        max_notifications=args.max_notifications,
    )
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Enron Email Pipeline")

    parser.add_argument(
        "--task", choices=["1", "2", "3", "4", "all"], default="all",
        help="Which task to run (1=extract+store, 3=duplicates, 4=notify, all=1+3+4)"
    )
    parser.add_argument("--maildir", default=DEFAULT_MAILDIR,
                        help="Path to enron maildir folder")
    parser.add_argument("--db", default=DEFAULT_DB,
                        help="SQLite database path")
    parser.add_argument("--mailboxes", nargs="+", default=None,
                        help="Specific mailbox names to process (default: auto sorted by size)")
    parser.add_argument("--min-mailboxes", type=int, default=DEFAULT_MIN_MAILBOXES,
                        help=f"Minimum mailboxes to process (default: {DEFAULT_MIN_MAILBOXES})")
    parser.add_argument("--min-emails", type=int, default=DEFAULT_MIN_EMAILS,
                        help=f"Minimum emails to insert (default: {DEFAULT_MIN_EMAILS})")
    parser.add_argument("--send-live", action="store_true",
                        help="Actually send notification emails (requires EMAIL_USER + EMAIL_APP_PASSWORD)")
    parser.add_argument("--notifier", choices=["smtp", "mcp"], default="smtp",
                        help="Notification backend (default: smtp)")
    parser.add_argument("--notify-email", default=None,
                        help="Override recipient email for live sends (use your own Gmail)")
    parser.add_argument("--max-notifications", type=int, default=None,
                        help="Max number of notifications to send (default: all)")

    args = parser.parse_args()

    if args.task in ("1", "2", "all"):
        print("=" * 50)
        print("TASK 1+2: Extract & Store")
        print("=" * 50)
        task_extract_store(args)

    if args.task in ("3", "all"):
        print("\n" + "=" * 50)
        print("TASK 3: Duplicate Detection")
        print("=" * 50)
        task_duplicates(args)

    if args.task in ("4", "all"):
        print("\n" + "=" * 50)
        print("TASK 4: Notifications")
        print("=" * 50)
        task_notify(args)

    print("\nDone.")


if __name__ == "__main__":
    main()
