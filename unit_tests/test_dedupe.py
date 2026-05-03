import sqlite3
import pytest
from datetime import datetime, timezone

from src.dedupe.dedupe import (
    EmailRow,
    _find_duplicate_clusters,
    _apply_flags,
)


BODY = "This is a sufficiently long email body used for deduplication testing purposes. " * 3


def email(mid: str, body: str = BODY, date: str = "2001-10-01") -> EmailRow:
    return EmailRow(mid, date, "Subject", "a@b.com", body, "subject")


# ── _find_duplicate_clusters ─────────────────────────────────────────────────

def test_find_clusters_identical_bodies():
    clusters = _find_duplicate_clusters([email("<a>"), email("<b>")])
    assert len(clusters) == 1
    assert len(clusters[0]) == 2


def test_find_clusters_different_bodies():
    clusters = _find_duplicate_clusters([
        email("<a>", BODY),
        email("<b>", "Completely unrelated content xyz abc 123 nothing in common."),
    ])
    assert clusters == []


def test_find_clusters_short_body_skipped():
    clusters = _find_duplicate_clusters([email("<a>", "Short"), email("<b>", "Short")])
    assert clusters == []


def test_find_clusters_original_is_earliest():
    clusters = _find_duplicate_clusters([
        email("<later>",   BODY, "2001-10-02"),
        email("<earlier>", BODY, "2001-10-01"),
    ])
    assert clusters[0][0].message_id == "<earlier>"


# ── _apply_flags ─────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    from src.db.store import get_connection, init_db, insert_record
    c = get_connection(tmp_path / "test.db")
    init_db(c)
    c.row_factory = sqlite3.Row

    def _insert(mid):
        insert_record(c, {
            "message_id": mid,
            "date": datetime(2001, 10, 1, tzinfo=timezone.utc),
            "from_address": "a@b.com",
            "to_addresses": ["b@c.com"],
            "cc_addresses": [], "bcc_addresses": [],
            "subject": "S", "subject_normalized": "s", "body": "B",
            "source_file": "f",
            "x_from": "", "x_to": "", "x_cc": "", "x_bcc": "",
            "x_folder": "", "x_origin": "", "content_type": "",
            "has_attachment": False, "forwarded_content": "", "quoted_content": "", "headings": "",
        })

    _insert("<orig>")
    _insert("<dup>")
    yield c
    c.close()


def test_apply_flags_marks_duplicate(db):
    orig = EmailRow("<orig>", "2001-10-01", "S", "a@b.com", "B", "s")
    dup  = EmailRow("<dup>",  "2001-10-02", "S", "a@b.com", "B", "s")
    _apply_flags(db, [(orig, dup, 95.0)])
    row = db.execute(
        "SELECT is_duplicate, duplicate_of, similarity_score FROM emails WHERE message_id='<dup>'"
    ).fetchone()
    assert row["is_duplicate"] == 1
    assert row["duplicate_of"] == "<orig>"
    assert abs(row["similarity_score"] - 95.0) < 0.01


def test_apply_flags_original_unchanged(db):
    orig = EmailRow("<orig>", "2001-10-01", "S", "a@b.com", "B", "s")
    dup  = EmailRow("<dup>",  "2001-10-02", "S", "a@b.com", "B", "s")
    _apply_flags(db, [(orig, dup, 95.0)])
    row = db.execute("SELECT is_duplicate FROM emails WHERE message_id='<orig>'").fetchone()
    assert row["is_duplicate"] == 0
