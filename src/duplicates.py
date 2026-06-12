import csv
import logging
import os
import re
import sqlite3
from collections import defaultdict

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

SUBJECT_PREFIX = re.compile(r"^(re|fwd?|fw)\s*:\s*", re.IGNORECASE)
SIMILARITY_THRESHOLD = 90.0


def normalize_subject(subject: str) -> str:
    """Strip Re:/Fwd:/Fw: prefixes and lowercase."""
    if not subject:
        return ""
    s = subject.strip()
    while SUBJECT_PREFIX.match(s):
        s = SUBJECT_PREFIX.sub("", s).strip()
    return s.lower()


def _get_original(conn: sqlite3.Connection, message_id: str) -> str | None:
    """Walk up duplicate_of chain to find the true original (is_duplicate=0)."""
    visited = set()
    current = message_id
    while current:
        if current in visited:
            logger.warning("Cycle detected in duplicate chain at %s", current)
            return None
        visited.add(current)
        row = conn.execute(
            "SELECT is_duplicate, duplicate_of FROM emails WHERE message_id = ?",
            (current,),
        ).fetchone()
        if row is None:
            return None
        if row["is_duplicate"] == 0:
            return current
        current = row["duplicate_of"]
    return None


def _repoint_children(conn: sqlite3.Connection, old_ref: str, new_ref: str) -> None:
    """Update all emails pointing to old_ref to point to new_ref instead."""
    conn.execute(
        "UPDATE emails SET duplicate_of = ? WHERE duplicate_of = ?",
        (new_ref, old_ref),
    )


def detect_duplicates(conn: sqlite3.Connection) -> list[dict]:
    """
    Scan DB for duplicate emails. Only considers emails with is_duplicate=0.
    Groups by (from_user_id, normalized_subject), fuzzy-matches bodies.
    Returns list of flagged duplicate records.
    """
    rows = conn.execute(
        """
        SELECT e.message_id, e.date, e.from_user_id, e.subject, e.body,
               u.email AS from_address
        FROM emails e
        JOIN users u ON e.from_user_id = u.user_id
        WHERE e.is_duplicate = 0
        ORDER BY e.from_user_id, e.date
        """
    ).fetchall()

    # Group by (from_user_id, normalized_subject)
    groups: dict[tuple, list] = defaultdict(list)
    for row in rows:
        key = (row["from_user_id"], normalize_subject(row["subject"] or ""))
        groups[key].append(dict(row))

    flagged = []
    group_stats = []

    for key, candidates in groups.items():
        if len(candidates) < 2:
            continue

        # Sort by date ascending — earliest is the original
        candidates.sort(key=lambda r: r["date"] or "")

        # Find duplicate clusters via fuzzy body matching
        # original_idx tracks which candidate is the original for each cluster
        cluster_original = {}  # candidate index → original index

        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                body_i = (candidates[i]["body"] or "").strip()
                body_j = (candidates[j]["body"] or "").strip()
                score = fuzz.ratio(body_i, body_j)
                if score >= SIMILARITY_THRESHOLD:
                    # i is earlier (sorted by date), so i is the original
                    orig_idx = cluster_original.get(i, i)
                    cluster_original[j] = orig_idx

        if not cluster_original:
            continue

        group_flagged = []
        for dup_idx, orig_idx in cluster_original.items():
            dup = candidates[dup_idx]
            orig = candidates[orig_idx]

            body_dup = (dup["body"] or "").strip()
            body_orig = (orig["body"] or "").strip()
            score = fuzz.ratio(body_dup, body_orig)

            # Verify original is truly not a duplicate (walk chain)
            true_original_id = _get_original(conn, orig["message_id"])
            if true_original_id is None:
                true_original_id = orig["message_id"]

            # Flag in DB
            conn.execute(
                """
                UPDATE emails
                SET is_duplicate = 1,
                    duplicate_of = ?,
                    similarity_score = ?
                WHERE message_id = ?
                """,
                (true_original_id, score, dup["message_id"]),
            )

            # Re-point any emails that previously pointed to this duplicate
            _repoint_children(conn, dup["message_id"], true_original_id)

            group_flagged.append({
                "duplicate_message_id": dup["message_id"],
                "original_message_id": true_original_id,
                "subject": dup["subject"],
                "from_address": dup["from_address"],
                "duplicate_date": dup["date"],
                "original_date": orig["date"],
                "similarity_score": round(score, 2),
            })
            flagged.append(group_flagged[-1])

        if group_flagged:
            group_stats.append(len(group_flagged) + 1)  # +1 for original

    conn.commit()

    # Print stats
    total_groups = len(group_stats)
    total_flagged = len(flagged)
    avg_size = sum(group_stats) / len(group_stats) if group_stats else 0

    print("\n=== Duplicate Detection Stats ===")
    print(f"Groups found  : {total_groups}")
    print(f"Emails flagged: {total_flagged}")
    print(f"Avg group size: {avg_size:.2f}")

    return flagged


def write_report(flagged: list[dict], output_path: str) -> None:
    """Write duplicates_report.csv."""
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    fields = [
        "duplicate_message_id", "original_message_id", "subject",
        "from_address", "duplicate_date", "original_date", "similarity_score",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(flagged)
    print(f"Report written: {output_path} ({len(flagged)} rows)")
