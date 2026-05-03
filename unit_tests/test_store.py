import sqlite3
import pytest
from datetime import datetime, timezone

from src.db.store import get_connection, init_db, insert_record, bulk_insert


@pytest.fixture
def conn(tmp_path):
    c = get_connection(tmp_path / "test.db")
    init_db(c)
    yield c
    c.close()


def make_record(**overrides) -> dict:
    base = {
        "message_id":         "<test-001@example.com>",
        "date":               datetime(2001, 10, 1, 10, 0, tzinfo=timezone.utc),
        "from_address":       "sender@example.com",
        "to_addresses":       ["recipient@example.com"],
        "cc_addresses":       [],
        "bcc_addresses":      [],
        "subject":            "Test Subject",
        "subject_normalized": "Test Subject",
        "body":               "Body text.",
        "source_file":        "test-mb/1.",
        "x_from": "", "x_to": "", "x_cc": "", "x_bcc": "",
        "x_folder": "", "x_origin": "", "content_type": "text/plain",
        "has_attachment":     False,
        "forwarded_content":  "",
        "quoted_content":     "",
        "headings":           "",
    }
    base.update(overrides)
    return base


def test_init_db_idempotent(tmp_path):
    c = get_connection(tmp_path / "idem.db")
    init_db(c)
    init_db(c)  # must not raise
    c.close()


def test_insert_record_returns_true_on_first_insert(conn):
    assert insert_record(conn, make_record()) is True


def test_insert_record_returns_false_on_duplicate(conn):
    rec = make_record()
    insert_record(conn, rec)
    assert insert_record(conn, rec) is False


def test_insert_record_persists_fields(conn):
    rec = make_record()
    insert_record(conn, rec)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM emails WHERE message_id=?", (rec["message_id"],)).fetchone()
    assert row["from_address"] == "sender@example.com"
    assert row["subject"] == "Test Subject"
    assert row["has_attachment"] == 0


def test_insert_record_stores_recipients(conn):
    rec = make_record(
        to_addresses=["to@example.com"],
        cc_addresses=["cc@example.com"],
        bcc_addresses=["bcc@example.com"],
    )
    insert_record(conn, rec)
    rows = conn.execute(
        "SELECT field, address FROM email_recipients WHERE message_id=? ORDER BY field",
        (rec["message_id"],),
    ).fetchall()
    fields = {r[0]: r[1] for r in rows}
    assert fields["to"] == "to@example.com"
    assert fields["cc"] == "cc@example.com"
    assert fields["bcc"] == "bcc@example.com"


def test_bulk_insert_counts(conn):
    existing = make_record()
    insert_record(conn, existing)
    new = make_record(message_id="<new@example.com>")
    inserted, skipped = bulk_insert(conn, [existing, new])
    assert inserted == 1
    assert skipped == 1
