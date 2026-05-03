"""
Duplicate detection for the Enron email pipeline.

Strategy:
  1. Group emails by (from_address, subject_normalized).
  2. Within each group, pairwise fuzzy-match body text (rapidfuzz token_sort_ratio).
  3. Union-Find clusters emails with similarity >= THRESHOLD.
  4. In each cluster mark the earliest email as original; flag all others as duplicates.
  5. Write results back to the DB and to duplicates_report.csv.
"""

import csv
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import fuzz

logger = logging.getLogger(__name__)

DB_PATH     = Path(__file__).parents[2] / "data" / "enron.db"
REPORT_PATH = Path(__file__).parents[2] / "duplicates_report.csv"
THRESHOLD   = 90.0   # minimum similarity % to call two emails duplicates
MIN_BODY_LEN = 20    # ignore near-empty bodies (signatures, blank emails)


# ── Union-Find ────────────────────────────────────────────────────────────────

class _UF:
    def __init__(self, keys):
        self._parent = {k: k for k in keys}

    def find(self, k):
        while self._parent[k] != k:
            self._parent[k] = self._parent[self._parent[k]]
            k = self._parent[k]
        return k

    def union(self, a, b):
        self._parent[self.find(a)] = self.find(b)

    def clusters(self):
        groups: dict[str, list] = {}
        for k in self._parent:
            root = self.find(k)
            groups.setdefault(root, []).append(k)
        return [v for v in groups.values() if len(v) > 1]


# ── Data container ────────────────────────────────────────────────────────────

@dataclass
class EmailRow:
    message_id:         str
    date:               str
    subject:            str
    from_address:       str
    body:               str
    subject_normalized: str


# ── Core logic ────────────────────────────────────────────────────────────────

def _similarity(a: str, b: str) -> float:
    """token_sort_ratio handles word-order differences and minor edits."""
    return fuzz.token_sort_ratio(a, b)


def _find_duplicate_clusters(emails: list[EmailRow]) -> list[list[EmailRow]]:
    """
    Within a candidate group (same sender + normalized subject),
    cluster emails whose bodies are >= THRESHOLD similar.
    Returns only clusters of size >= 2.
    """
    ids  = [e.message_id for e in emails]
    idx  = {e.message_id: e for e in emails}
    uf   = _UF(ids)

    for i in range(len(emails)):
        body_i = emails[i].body.strip()
        if len(body_i) < MIN_BODY_LEN:
            continue
        for j in range(i + 1, len(emails)):
            body_j = emails[j].body.strip()
            if len(body_j) < MIN_BODY_LEN:
                continue
            score = _similarity(body_i, body_j)
            if score >= THRESHOLD:
                uf.union(emails[i].message_id, emails[j].message_id)

    raw_clusters = uf.clusters()
    result = []
    for cluster in raw_clusters:
        members = sorted([idx[mid] for mid in cluster], key=lambda e: e.date)
        original = members[0]
        orig_body = original.body.strip()
        # Keep only duplicates whose similarity to the ORIGINAL meets threshold.
        # Union-Find can create transitive chains where A≈B≈C but A-C < threshold.
        confirmed = [original]
        for m in members[1:]:
            if len(m.body.strip()) >= MIN_BODY_LEN and _similarity(orig_body, m.body.strip()) >= THRESHOLD:
                confirmed.append(m)
        if len(confirmed) > 1:
            result.append(confirmed)
    return result


# ── DB helpers ────────────────────────────────────────────────────────────────

def _load_candidate_groups(conn: sqlite3.Connection) -> dict[tuple, list[EmailRow]]:
    """
    Return dict keyed by (from_address, subject_normalized) → list[EmailRow].
    Only fetches groups with >= 2 emails to avoid loading the full table.
    """
    rows = conn.execute("""
        SELECT message_id, date, subject, from_address, body, subject_normalized
        FROM emails
        WHERE subject_normalized != ''
          AND is_duplicate = 0
        ORDER BY from_address, subject_normalized, date
    """).fetchall()

    groups: dict[tuple, list[EmailRow]] = {}
    for r in rows:
        key = (r["from_address"], r["subject_normalized"])
        groups.setdefault(key, []).append(EmailRow(
            message_id         = r["message_id"],
            date               = r["date"],
            subject            = r["subject"],
            from_address       = r["from_address"],
            body               = r["body"] or "",
            subject_normalized = r["subject_normalized"],
        ))

    # Keep only groups with >1 email
    return {k: v for k, v in groups.items() if len(v) > 1}


def _apply_flags(
    conn: sqlite3.Connection,
    clusters: list[tuple[EmailRow, EmailRow, float]],  # (original, duplicate, score)
) -> None:
    conn.executemany(
        """
        UPDATE emails
        SET is_duplicate = 1, duplicate_of = ?, similarity_score = ?
        WHERE message_id = ?
        """,
        [(orig.message_id, score, dup.message_id) for orig, dup, score in clusters],
    )
    conn.commit()


def _write_report(
    report_path: Path,
    clusters: list[tuple[EmailRow, EmailRow, float]],
) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "duplicate_message_id", "original_message_id", "subject",
            "from_address", "duplicate_date", "original_date", "similarity_score",
        ])
        writer.writeheader()
        for orig, dup, score in clusters:
            writer.writerow({
                "duplicate_message_id": dup.message_id,
                "original_message_id":  orig.message_id,
                "subject":              dup.subject,
                "from_address":         dup.from_address,
                "duplicate_date":       dup.date,
                "original_date":        orig.date,
                "similarity_score":     round(score, 2),
            })


# ── Entry point ───────────────────────────────────────────────────────────────

def run_deduplication(
    db_path: Path = DB_PATH,
    report_path: Path = REPORT_PATH,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    logger.info("Loading candidate groups from DB...")
    groups = _load_candidate_groups(conn)
    logger.info("Candidate groups (same sender+subject): %d", len(groups))

    all_pairs: list[tuple[EmailRow, EmailRow, float]] = []
    total_groups = len(groups)

    for i, (key, emails) in enumerate(groups.items()):
        if i % 500 == 0:
            logger.info("Clustering groups: %d / %d", i, total_groups)

        clusters = _find_duplicate_clusters(emails)
        for cluster in clusters:
            original = cluster[0]
            for dup in cluster[1:]:
                score = _similarity(original.body.strip(), dup.body.strip())
                all_pairs.append((original, dup, score))

    logger.info("Total duplicate pairs found: %d", len(all_pairs))

    if not all_pairs:
        logger.info("No duplicates detected.")
        conn.close()
        return

    _apply_flags(conn, all_pairs)
    _write_report(report_path, all_pairs)

    # Summary stats
    total_flagged = len(all_pairs)
    unique_originals = len({orig.message_id for orig, _, _ in all_pairs})
    avg_score = sum(s for _, _, s in all_pairs) / total_flagged
    scores_100 = sum(1 for _, _, s in all_pairs if s == 100.0)

    print(f"\n{'-'*52}")
    print(f"Duplicate groups found  : {unique_originals}")
    print(f"Total emails flagged    : {total_flagged}")
    print(f"Avg similarity score    : {avg_score:.1f}%")
    print(f"Exact matches (100%)    : {scores_100}")
    print(f"Report written to       : {report_path}")
    print(f"{'-'*52}\n")

    conn.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    run_deduplication()
