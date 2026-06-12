# AI Usage Documentation

This project was built with Claude (claude-sonnet-4-6) via Claude Code CLI as the primary development assistant.

---

## How AI Was Used

### Prompting Strategy

The development session was conversational and iterative. Rather than writing prompts in batch, each component was developed in a tight loop:

1. **Describe the goal** — e.g. "write the extractor, it should parse one file at a time and return a dict"
2. **Review the output** — read the generated code and ask follow-up questions
3. **Correct and iterate** — e.g. "run extraction should be abstract — the caller counts, not the function"
4. **Test immediately** — ask Claude to write tests in parallel, run them, fix failures

This kept each piece focused and testable before moving to the next.

### Key Design Decisions Made With AI Assistance

| Decision | Rationale discussed |
|----------|---------------------|
| Generator-based file iterator | Avoid pre-building a 500k path list in memory |
| Stop criteria: both AND conditions | Smallest mailboxes first, stop mid-mailbox when both met |
| Ascending mailbox sort | Smallest mailboxes → fastest ramp to 10k; descending picked the 28k-email kaminski-v box and ran for 40+ minutes |
| `\\?\` long-path prefix | Windows strips trailing dots in `os.path.abspath("1.")` → `"1"`, breaking file opens |
| `_get_original()` + `_repoint_children()` | Ensures `duplicate_of` always points to true original, not an intermediate in a chain |
| Shared `EmailComposer` class | Both SMTP and MCP backends use the same HTML template — avoids duplication |
| `--notify-email` override | Enron addresses don't exist; redirect live sends to own Gmail to avoid bounces |
| `--max-notifications 3` | Prevent Gmail rate-limit suspension during demo |

### Iterations and Corrections

Several bugs were caught and fixed through the testing cycle:

- **Trailing-dot filenames**: `os.path.abspath` strips trailing dots on Windows (e.g. `1.` → `1`). Fixed by manually constructing absolute paths with `os.getcwd()` string concatenation.
- **Relative `..` paths with `\\?\` prefix**: The prefix doesn't support `..` directory components. Fixed by running `os.path.normpath()` before adding the prefix.
- **`FORWARD_MARKERS` regex**: `"Forwarded by John/Enron"` wasn't matching. Fixed by changing pattern to `Forwarded by\b.*`.
- **`sendmail` argument shape**: `sendmail(from, [to_list], body)` — test was asserting on `call_args[0]` instead of `call_args[0][1]` for the recipient list.
- **Descending mailbox sort (performance bug)**: Pipeline processed `kaminski-v` (28k emails) as the first mailbox before reaching min criteria. Flipping to ascending sort resolved this — 23 small mailboxes hit 10k emails comfortably.
- **Gmail App Password authentication**: Multiple App Passwords failed before a valid one was generated. The fix was regenerating the password in the Google Account security panel.

---

## MCP (Model Context Protocol) Integration

### What is Gmail MCP?

The Gmail MCP server is an **open-source Node.js process** (not from Google) that exposes Gmail send/read/list operations as structured tools that Claude Code can invoke via the MCP protocol. It authenticates via Google OAuth 2.0.

Claude Code registers MCP servers in `.claude/mcp.json` and calls their tools via `claude mcp call <server> <tool> --input '...'`.

### How It Differs from SMTP

| | SMTP (`notifier_smtp.py`) | MCP (`notifier_mcp.py`) |
|---|---|---|
| Auth | Gmail App Password | Google OAuth 2.0 |
| Setup | Simple `.env` file | Install Node.js + MCP server + OAuth flow |
| Used by | Any Python process | Claude Code only |
| Default | ✅ Yes | No (use `--notifier mcp`) |

SMTP was chosen as the default because it requires less setup (just an App Password) and works outside of Claude Code. MCP is available as an alternate backend for environments where the MCP server is already configured.

### MCP Setup

To use the MCP backend:

1. Install the Gmail MCP server:
   ```bash
   npx @gptscript-ai/gmail-mcp setup
   ```

2. Copy `mcp_config.json.example` to `.claude/mcp.json` and fill in OAuth credentials.

3. Run with:
   ```bash
   python main.py --task 4 --send-live --notifier mcp --notify-email you@gmail.com
   ```

---

## Live Email Confirmation

Three live notification emails were sent successfully to `chandanaws1998@gmail.com` on 2026-06-12 via Gmail SMTP. The emails include:

- Dark gradient header with "Duplicate Email Detected" banner
- Similarity score badge (e.g. 95.2%)
- Side-by-side red/green cards for flagged vs original email
- Monospace Message-ID display
- Plain text fallback for non-HTML clients

The send log is at `output/send_log.csv`.

---

## What AI Did Not Do

- The Enron dataset download and setup was done manually
- Gmail App Password was generated manually in the Google Account security panel
- Final architectural decisions (ascending vs descending sort, AND vs OR stop criteria) were made by the developer after discussing trade-offs with the AI
