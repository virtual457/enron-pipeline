# Enron Email Pipeline

End-to-end data pipeline over the Enron email dataset. Extracts raw RFC 2822 email files, stores them in a normalized SQLite database, detects duplicate emails via fuzzy matching, and sends notification emails to flagged senders.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Download the Enron dataset and place it at:
#    data/maildir/   (each subdirectory is one employee's mailbox)

# 3. Copy and fill in credentials
cp .env.example .env
# Edit .env with your Gmail address and App Password

# 4. Run the full pipeline
python main.py --task all
```

## Project Structure

```
enron-pipeline/
├── main.py                   # CLI entry point
├── schema.sql                # SQLite schema (3 tables, 7 indexes)
├── sample_queries.sql        # Example analytical queries
├── requirements.txt
├── src/
│   ├── extractor.py          # Task 1: parse RFC 2822 email files
│   ├── database.py           # Task 2: SQLite storage layer
│   ├── duplicates.py         # Task 3: fuzzy duplicate detection
│   ├── email_composer.py     # Shared .eml builder (HTML + plain text)
│   ├── notifier.py           # Task 4: orchestration + send log
│   ├── notifier_smtp.py      # Gmail SMTP backend
│   └── notifier_mcp.py       # Gmail MCP backend (alternate)
├── tests/
│   ├── test_extractor.py     # 32 tests
│   ├── test_pipeline.py      # 7 tests
│   └── test_notifier.py      # 20 tests
├── output/
│   ├── replies/              # Generated .eml draft files
│   ├── duplicates_report.csv
│   └── send_log.csv
└── data/
    └── maildir/              # Enron dataset (not committed)
```

## CLI Reference

```
python main.py [--task TASK] [--maildir PATH] [--db PATH]
               [--min-mailboxes N] [--min-emails N]
               [--send-live] [--notifier smtp|mcp]
               [--notify-email EMAIL] [--max-notifications N]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--task` | `all` | `1` (extract+store), `3` (duplicates), `4` (notify), `all` |
| `--maildir` | `data/maildir` | Path to Enron maildir |
| `--db` | `enron.db` | SQLite database path |
| `--min-mailboxes` | `5` | Stop after processing this many mailboxes (AND min-emails) |
| `--min-emails` | `10000` | Stop after inserting this many emails (AND min-mailboxes) |
| `--send-live` | off | Actually send emails (requires `.env` credentials) |
| `--notifier` | `smtp` | Backend: `smtp` (default) or `mcp` |
| `--notify-email` | none | Override recipient — use your own Gmail to avoid bounces |
| `--max-notifications` | all | Cap on live sends per run (use `3` for demos) |

## Environment Setup

Create a `.env` file (never commit this):

```
EMAIL_USER=you@gmail.com
EMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

Get a Gmail App Password at: Google Account → Security → 2-Step Verification → App Passwords.

## Database Schema

**users** — normalized sender/recipient registry  
**emails** — one row per unique Message-ID with all parsed fields  
**email_recipients** — normalized To/CC/BCC rows with `type` enum  

Key columns on `emails`:
- `is_duplicate` / `duplicate_of` — set by duplicate detection; `duplicate_of` always points to the true original (chain-resolved)
- `notification_sent` / `notification_date` — set after a notification email is dispatched

## Architecture

### Task 1+2 — Extract & Store

- `sorted_mailboxes()` sorts mailboxes ascending by email count (smallest first) for fast ramp-up
- `iter_files()` is a generator — no pre-built path list, memory-efficient for 500k+ files
- Stops as soon as **both** `--min-mailboxes` AND `--min-emails` are satisfied simultaneously
- Windows trailing-dot filenames (e.g. `1.`) handled via `\\?\` long-path prefix — `os.path.abspath` is avoided because it strips trailing dots on Windows
- Date normalization to UTC using `dateutil` with a custom TZ abbreviation map (PST/EST/CDT/etc.)

### Task 3 — Duplicate Detection

- Groups by `(from_address, normalized_subject)` — strips Re:/Fwd: prefixes before grouping
- Pairwise body comparison with `rapidfuzz.fuzz.ratio ≥ 90%`
- Chain integrity: when email B is a duplicate of A, and A later proves to be a duplicate of X, all children of A are repointed to X (`_repoint_children`)
- Only non-duplicate emails are candidates for new groups (prevents chain inflation)

### Task 4 — Notifications

- Always generates `.eml` drafts in `output/replies/` (dry run is the default)
- `--send-live` enables live SMTP delivery
- `EmailComposer` builds beautiful HTML + plain text multipart email
- `--max-notifications 3` limits sends per run (prevents Gmail rate-limit suspension)
- `--notify-email` redirects delivery to your own inbox (Enron addresses no longer exist)

## Running Tests

```bash
pip install pytest
pytest tests/ -v
```

All 59 tests pass. Tests use in-memory SQLite and mocked SMTP — no network calls.

## Sample Queries

See `sample_queries.sql` for:
- Top 10 email senders
- Emails in a date range
- Threads with CC recipients

## MCP Backend (Alternate)

The pipeline includes a second notifier backend (`notifier_mcp.py`) that calls the Gmail MCP server via Claude Code's `claude mcp call` subprocess interface.

See `mcp_config.json.example` for setup. Switch with `--notifier mcp`.
