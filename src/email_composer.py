import os
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


class EmailComposer:
    """Builds notification .eml content for a flagged duplicate email."""

    PLAIN_TEMPLATE = """\
This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

  Your Email (Flagged):
    Message-ID:  {duplicate_message_id}
    Date Sent:   {duplicate_date}
    Subject:     {subject}

  Original Email on Record:
    Message-ID:  {original_message_id}
    Date Sent:   {original_date}

  Similarity Score: {similarity_score}%

If this was NOT a duplicate and you intended to send this email,
please reply with CONFIRM to restore it to active status.
No action is required if this is indeed a duplicate.
"""

    HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: #f0f2f5;
    padding: 32px 16px;
    color: #1a1a2e;
  }}
  .wrapper {{
    max-width: 600px;
    margin: 0 auto;
  }}
  .header {{
    background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
    border-radius: 12px 12px 0 0;
    padding: 32px;
    text-align: center;
  }}
  .header .icon {{
    font-size: 40px;
    margin-bottom: 12px;
  }}
  .header h1 {{
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
    letter-spacing: 0.5px;
  }}
  .header p {{
    color: #a8b2d8;
    font-size: 13px;
    margin-top: 6px;
  }}
  .badge {{
    display: inline-block;
    background: #e63946;
    color: white;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
    text-transform: uppercase;
    padding: 4px 12px;
    border-radius: 20px;
    margin-top: 12px;
  }}
  .body {{
    background: #ffffff;
    padding: 32px;
    border-left: 1px solid #e2e8f0;
    border-right: 1px solid #e2e8f0;
  }}
  .intro {{
    font-size: 15px;
    color: #4a5568;
    line-height: 1.6;
    margin-bottom: 28px;
    padding: 16px;
    background: #fff8e1;
    border-left: 4px solid #f6ad55;
    border-radius: 4px;
  }}
  .score-bar {{
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    padding: 20px 24px;
    margin-bottom: 24px;
    text-align: center;
  }}
  .score-bar .label {{
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #718096;
    margin-bottom: 8px;
  }}
  .score-bar .value {{
    font-size: 42px;
    font-weight: 800;
    color: #e63946;
    line-height: 1;
  }}
  .score-bar .sub {{
    font-size: 12px;
    color: #a0aec0;
    margin-top: 4px;
  }}
  .cards {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 16px;
    margin-bottom: 24px;
  }}
  .card {{
    border-radius: 10px;
    padding: 18px;
    border: 1px solid #e2e8f0;
  }}
  .card.flagged {{
    background: #fff5f5;
    border-color: #fed7d7;
  }}
  .card.original {{
    background: #f0fff4;
    border-color: #c6f6d5;
  }}
  .card .card-title {{
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin-bottom: 12px;
  }}
  .card.flagged .card-title {{ color: #e53e3e; }}
  .card.original .card-title {{ color: #38a169; }}
  .card .field {{
    margin-bottom: 8px;
  }}
  .card .field-label {{
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: #a0aec0;
    margin-bottom: 2px;
  }}
  .card .field-value {{
    font-size: 12px;
    color: #2d3748;
    word-break: break-all;
    font-family: 'SF Mono', 'Fira Code', monospace;
  }}
  .subject-box {{
    background: #ebf4ff;
    border: 1px solid #bee3f8;
    border-radius: 8px;
    padding: 14px 18px;
    margin-bottom: 24px;
  }}
  .subject-box .label {{
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #4299e1;
    margin-bottom: 4px;
  }}
  .subject-box .value {{
    font-size: 15px;
    font-weight: 600;
    color: #2b6cb0;
  }}
  .action-box {{
    background: #f7fafc;
    border: 1px dashed #cbd5e0;
    border-radius: 10px;
    padding: 20px;
    text-align: center;
    margin-bottom: 24px;
  }}
  .action-box p {{
    font-size: 14px;
    color: #4a5568;
    line-height: 1.6;
    margin-bottom: 12px;
  }}
  .confirm-btn {{
    display: inline-block;
    background: #2d3748;
    color: white;
    font-size: 13px;
    font-weight: 600;
    padding: 10px 24px;
    border-radius: 6px;
    text-decoration: none;
    letter-spacing: 0.5px;
  }}
  .footer {{
    background: #f7fafc;
    border: 1px solid #e2e8f0;
    border-top: none;
    border-radius: 0 0 12px 12px;
    padding: 20px 32px;
    text-align: center;
  }}
  .footer p {{
    font-size: 12px;
    color: #a0aec0;
    line-height: 1.6;
  }}
  .footer .system-name {{
    font-weight: 600;
    color: #718096;
  }}
</style>
</head>
<body>
<div class="wrapper">

  <!-- Header -->
  <div class="header">
    <div class="icon">&#x26A0;&#xFE0F;</div>
    <h1>Duplicate Email Detected</h1>
    <p>Automated notification from the Enron Email Deduplication System</p>
    <span class="badge">Action Required</span>
  </div>

  <!-- Body -->
  <div class="body">

    <div class="intro">
      Your email has been flagged as a <strong>potential duplicate</strong> of an existing message
      in our system. Please review the details below and take action if needed.
    </div>

    <!-- Similarity Score -->
    <div class="score-bar">
      <div class="label">Similarity Score</div>
      <div class="value">{similarity_score}%</div>
      <div class="sub">Body content match with original email</div>
    </div>

    <!-- Subject -->
    <div class="subject-box">
      <div class="label">Email Subject</div>
      <div class="value">{subject}</div>
    </div>

    <!-- Cards -->
    <div class="cards">
      <div class="card flagged">
        <div class="card-title">&#x1F6A9; Your Email (Flagged)</div>
        <div class="field">
          <div class="field-label">Message ID</div>
          <div class="field-value">{duplicate_message_id}</div>
        </div>
        <div class="field">
          <div class="field-label">Date Sent</div>
          <div class="field-value">{duplicate_date}</div>
        </div>
      </div>
      <div class="card original">
        <div class="card-title">&#x2705; Original on Record</div>
        <div class="field">
          <div class="field-label">Message ID</div>
          <div class="field-value">{original_message_id}</div>
        </div>
        <div class="field">
          <div class="field-label">Date Sent</div>
          <div class="field-value">{original_date}</div>
        </div>
      </div>
    </div>

    <!-- Action -->
    <div class="action-box">
      <p>
        If this was <strong>NOT a duplicate</strong> and you intended to send this email,
        reply with <strong>CONFIRM</strong> to restore it to active status.
      </p>
      <span class="confirm-btn">Reply: CONFIRM</span>
    </div>

  </div>

  <!-- Footer -->
  <div class="footer">
    <p>
      This is an automated message from the
      <span class="system-name">Enron Email Deduplication System</span>.<br>
      No action is required if this email is indeed a duplicate.
    </p>
  </div>

</div>
</body>
</html>
"""

    def build(self, duplicate: dict, original: dict, score: float) -> str:
        """Build a multipart .eml with plain text + HTML parts."""
        subject = duplicate.get("subject") or ""
        to_addr = duplicate.get("from_address", "")
        now = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

        plain = self.PLAIN_TEMPLATE.format(
            duplicate_message_id=duplicate["message_id"],
            duplicate_date=duplicate.get("date", ""),
            subject=subject,
            original_message_id=original["message_id"],
            original_date=original.get("date", ""),
            similarity_score=round(score, 1),
        )

        html = self.HTML_TEMPLATE.format(
            duplicate_message_id=duplicate["message_id"],
            duplicate_date=duplicate.get("date", ""),
            subject=subject,
            original_message_id=original["message_id"],
            original_date=original.get("date", ""),
            similarity_score=round(score, 1),
        )

        msg = MIMEMultipart("alternative")
        msg["To"] = to_addr
        msg["Subject"] = f"[Duplicate Notice] Re: {subject}"
        msg["Date"] = now
        msg["References"] = duplicate["message_id"]
        msg["From"] = "Enron Dedup System <dedup-system@enron-pipeline.local>"

        msg.attach(MIMEText(plain, "plain"))
        msg.attach(MIMEText(html, "html"))

        return msg.as_string()

    def save_eml(self, eml_content: str, output_dir: str, message_id: str) -> str:
        """Write .eml file to output_dir. Returns the file path written."""
        os.makedirs(output_dir, exist_ok=True)
        safe_name = (
            message_id.replace("<", "").replace(">", "")
            .replace("/", "_").replace("\\", "_").replace(":", "_")
        )
        filepath = os.path.join(output_dir, f"{safe_name}.eml")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(eml_content)
        return filepath
