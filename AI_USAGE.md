# AI Usage Documentation

## 1. Tool Used

**Claude Code** (Anthropic) — CLI version, powered by `claude-sonnet-4-6` (Sonnet 4.6).  
All development was done interactively inside the Claude Code terminal session in VS Code on Windows 11.

---

## 2. Prompting Strategy

I broke the problem into four discrete tasks matching the assignment sections, prompting Claude Code task-by-task rather than dumping the entire spec at once. This kept responses focused and made debugging easier — when one task broke, the blast radius was limited to that module.

**Overall approach:**
1. Start with schema + database layer (foundation everything else depends on)
2. Build the extractor against a known-good sample file
3. Wire extraction → storage in `main.py` with early-stop logic
4. Implement duplicate detection as a standalone pass over the DB
5. Build the notification layer last, once the data was confirmed correct

---

## 3. Example Prompts

### Prompt 1 — Schema design
> *"Design a normalized SQLite schema for the Enron email dataset. I need to store: message_id (unique PK), date (UTC), from address, to/cc/bcc as related rows (not comma strings), subject, body, optional X-headers (x_from, x_to, x_cc, x_bcc, x_folder, x_origin), content_type, has_attachment boolean, forwarded_content, quoted_content, headings. Also add columns for duplicate detection: is_duplicate, duplicate_of (self-referencing FK), similarity_score, notification_sent, notification_date. Include all indexes the assignment requires."*

**Why:** Led with the full field list so Claude wouldn't have to guess. Mentioning "not comma strings" upfront prevented a common antipattern. Specifying the duplicate columns avoided a second schema migration later.

---

### Prompt 2 — Email parser with edge-case handling
> *"Write a Python function `parse_email(filepath, maildir_path)` that reads a raw RFC 2822 file and returns a dict with all mandatory and optional fields. Requirements: multi-encoding fallback (utf-8 → latin-1 → cp1252), parse dates to UTC ISO using dateutil with a custom tzinfos map for PST/EST/CDT, extract just the email address from From/To/CC headers (strip display names), split body into (body, forwarded_content, quoted_content) by detecting '--- Original Message ---' markers and '>' quoted lines, detect attachments from MIME or '&lt;&lt; File:' patterns, and raise ValueError on any missing mandatory field."*

**Why:** Listing every edge case in the prompt got correct handling on the first attempt rather than discovering missing cases during testing. Specifying `raise ValueError` (not `return None`) forced a clean error contract the pipeline could rely on.

---

### Prompt 3 — Fuzzy duplicate detection with chain integrity
> *"Implement `detect_duplicates(conn)` that groups emails by (from_user_id, normalized_subject — strip Re:/Fwd: prefixes), then pairwise fuzzy-matches bodies using rapidfuzz.fuzz.ratio >= 90. Within each group sort by date ascending so the earliest is the original. Mark later emails as duplicates (is_duplicate=1, duplicate_of=earliest message_id). Handle chains: if A is a duplicate of B, and B is later found to be a duplicate of X, repoint A → X. Only scan emails with is_duplicate=0 to avoid double-counting. Return a list of dicts for the CSV report."*

**Why:** The chain-integrity requirement was the hardest part. Spelling out the repointing rule (`_repoint_children`) in the prompt meant Claude implemented it correctly rather than leaving orphaned chains.

---

### Prompt 4 — HTML notification email template
> *"Write an `EmailComposer` class that builds a multipart/alternative .eml (plain text + HTML). The HTML should look professional: dark gradient header with 'Action Required' badge, large similarity score display in red, two side-by-side cards (flagged email in red tones, original in green tones), and a 'Reply: CONFIRM' action button. Fields to populate: duplicate_message_id, duplicate_date, original_message_id, original_date, subject, similarity_score. Also implement `save_eml(eml_content, output_dir, message_id)` that sanitizes the message_id into a safe filename."*

**Why:** Describing the visual design intent (not just the fields) produced a styled template rather than a plain table layout. Mentioning filename sanitization upfront avoided a crash on message IDs containing `<>/:\` characters.

---

### Prompt 5 — Windows trailing-dot filename handling
> *"On Windows, email files with trailing dots in the filename (e.g. `1.`) cannot be opened with the normal `open()` call — it silently maps to the wrong path. Write a `_win_path(path)` helper that prepends the `\\\\?\\` long-path prefix so Windows opens these files correctly. Note: `os.path.abspath` must NOT be used because it strips trailing dots."*

**Why:** This was a Windows-specific bug that took 20 minutes to diagnose. Once I understood the root cause I described it precisely, and Claude produced the correct solution immediately including the warning about `os.path.abspath`.

---

## 4. Iterations and Debugging

### Iteration 1 — Date parsing silently returning None

**What went wrong:** The initial `_parse_date` implementation used `email.utils.parsedate_to_datetime` which throws on timezone abbreviations like `PST` and `CDT` (not valid RFC 2822). About 30% of emails were failing the mandatory-date check and being logged as errors.

**How I diagnosed it:** Added a temporary counter to `task_extract_store` that printed the failure reason. Saw hundreds of `"Missing or unparseable Date"` lines, all from emails with `PST`/`CDT` in the Date header.

**Fix prompt:**
> *"Replace `email.utils.parsedate_to_datetime` with `dateutil.parser.parse` and pass a `tzinfos` dict mapping PST/PDT/MST/MDT/CST/CDT/EST/EDT to their correct `dateutil.tz.gettz` timezones. If parsing still fails, return None. Always convert to UTC before returning ISO format."*

The failure rate dropped from ~30% to under 0.5% (only genuinely malformed dates).

---

### Iteration 2 — Duplicate chain inflation

**What went wrong:** The first `detect_duplicates` implementation ran in a loop over all emails including ones already marked `is_duplicate=1`. On the second run (or when called after partial flagging), emails that were already duplicates got added to new groups, creating phantom chains where a duplicate pointed to another duplicate instead of the true original.

**How I diagnosed it:** Ran `detect_duplicates` twice on the same DB and compared the `duplicate_of` values. Saw entries like A → B → C where B was already flagged, instead of A → C and B → C.

**Fix prompt:**
> *"The query must filter `WHERE is_duplicate = 0` so already-flagged emails are never candidates for new groups. Additionally, after flagging a new duplicate, call `_repoint_children(conn, dup_message_id, true_original_id)` to update any emails that previously pointed to the newly flagged email so they now point to the true original."*

After the fix, running detection twice produced identical results (idempotent).

---

### Iteration 3 — MCP subprocess call format

**What went wrong:** The initial `notifier_mcp.py` used `claude --mcp-tool gmail send_email` (wrong CLI syntax). The subprocess returned exit code 1 with `"unknown flag: --mcp-tool"`.

**How I diagnosed it:** Checked `claude --help` and `claude mcp --help` in the terminal to find the correct subcommand structure.

**Fix:** Corrected to `claude mcp call gmail send_email --input '<json>'` which is the actual Claude Code MCP call syntax.

---

## 5. AI-Written vs Manually Written

| Component | AI-generated | Manual |
|---|---|---|
| `schema.sql` | 90% | 10% (added `notification_date` column manually after reviewing requirements) |
| `src/extractor.py` | 75% | 25% (`_win_path` logic required multiple manual iterations; timezone map tuned manually) |
| `src/database.py` | 100% | 0%  |
| `src/duplicates.py` | 70% | 30% (`_get_original` chain-walking loop and `_repoint_children` required manual debugging) |
| `src/email_composer.py` | 60% | 40% (HTML styling iterated heavily by hand to match design intent) |
| `src/notifier.py` | 80% | 20% |
| `src/notifier_smtp.py` | 85% | 15% |
| `src/notifier_mcp.py` | 65% | 35% (subprocess call format required manual research) |
| `main.py` | 80% | 20% |
| `tests/` | 70% | 30% (mock setup for SMTP context manager required manual fixes) |
| `README.md` | 75% | 25% |

**Overall estimate: ~75% AI-generated, ~25% manually written or significantly revised.**

---

## 6. Lessons Learned

**What worked well:**
- Task-by-task prompting kept context tight. Giving Claude one module at a time produced clean, focused code with minimal hallucinated imports.
- Describing the *why* (e.g., "must raise ValueError so the pipeline can catch it") not just the *what* consistently produced correct error contracts.
- Asking Claude to explain its approach before writing code (for the duplicate chain logic) caught a design flaw before any code was written.

**What was harder than expected:**
- Windows path edge cases (`trailing-dot filenames`, `\\?\` prefix) are not well-represented in training data. Claude's first two attempts were wrong and had to be manually debugged.
- The MCP subprocess invocation syntax required reading `claude --help` manually — Claude's knowledge of its own CLI flags was slightly out of date.
- HTML email rendering across clients (Gmail, Outlook) required manual CSS tweaks that AI suggestions didn't anticipate (e.g., `grid` layout not supported in some clients — had to fall back to table for the two-column card layout in production).

---

## 7. MCP Integration

### Server Chosen

**`@gongrzhe/server-gmail-autoauth-mcp`** — an open-source Gmail MCP server using OAuth2 with auto-authentication flow.

**Why this server:**
- Auto-auth flow handles the OAuth token refresh automatically — no manual token rotation.
- Available as an `npx` package, no local build required.
- Already configured in the global Claude Code MCP registry, confirmed working with `claude mcp list`.

---

### Setup Steps

1. **Install Node.js** (required for `npx`).

2. **Create a Google Cloud project** and enable the Gmail API:
   - Go to [console.cloud.google.com](https://console.cloud.google.com)
   - Create OAuth2 credentials (Desktop app type)
   - Download `credentials.json`

3. **Run the auth flow** once to generate a refresh token:
   ```bash
   npx -y @gongrzhe/server-gmail-autoauth-mcp auth
   ```
   This opens a browser for Google sign-in and saves the token locally.

4. **Register with Claude Code:**
   ```bash
   claude mcp add gmail -- npx -y @gongrzhe/server-gmail-autoauth-mcp
   ```

5. **Verify connection:**
   ```bash
   claude mcp list
   # gmail: node ... - ✓ Connected
   ```

6. **Project config** (`mcp_config.json.example`) shows the structure with placeholder credentials for reference.

---

### Example Prompts Used with MCP

**Prompt to test the MCP connection:**
> *"Use the gmail MCP tool to send a test email to gowdakeelarashivan.c@northeastern.edu with subject 'MCP Gmail Test — Enron Pipeline' and a short body confirming the MCP backend works."*

**Prompt to send a full HTML notification:**
> *"Use the gmail MCP send_email tool to send the duplicate notification email to chandanaws1998@gmail.com. Use the HTML from EmailComposer.HTML_TEMPLATE filled with this sample data: subject='Quarterly Energy Report Q3 2001', similarity_score=97.4, duplicate_message_id='&lt;45678901...&gt;', original_message_id='&lt;12345678...&gt;'. Send as multipart/alternative with both plain text and HTML body."*

---

### Issues Encountered

| Issue | Resolution |
|---|---|
| Initial subprocess call used wrong CLI flag (`--mcp-tool`) | Corrected to `claude mcp call <server> <tool> --input '<json>'` after reading `claude mcp --help` |
| OAuth token expired mid-session | Re-ran `npx @gongrzhe/server-gmail-autoauth-mcp auth` to refresh; auto-auth handles this on subsequent runs |
| Gmail blocked send from unrecognized app | Enabled "Less secure app access" temporarily; resolved properly by using App Passwords for SMTP backend |

---

### Successful Send Log

Two live emails sent and delivered during development, confirming end-to-end MCP integration:

```
# Test 1 — plain text confirmation
claude mcp call gmail send_email
→ Email sent successfully with ID: 19ebd240500b222a
  To: gowdakeelarashivan.c@northeastern.edu
  Subject: MCP Gmail Test — Enron Pipeline

# Test 2 — full HTML duplicate notification (EmailComposer template)
claude mcp call gmail send_email (multipart/alternative)
→ Email sent successfully with ID: 19ebd25857244e66
  To: chandanaws1998@gmail.com
  Subject: [Duplicate Notice] Re: Quarterly Energy Report Q3 2001
  Similarity Score displayed: 97.4%
```

Both emails were received and rendered correctly in Gmail with the full HTML layout (gradient header, score bar, flagged/original cards, CONFIRM button).
