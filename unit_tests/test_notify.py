import sqlite3
import pytest
from datetime import datetime, timezone

from src.notify.notify import (
    DuplicateRecord,
    load_pending_duplicates,
    mark_notification_sent,
    write_eml_draft,
)


def dup_record(**overrides) -> DuplicateRecord:
    base = DuplicateRecord(
        dup_message_id="<dup@example.com>",
        orig_message_id="<orig@example.com>",
        subject="Budget Meeting",
        from_address="sender@example.com",
        dup_date="2001-10-02T10:00:00+00:00",
        orig_date="2001-10-01T10:00:00+00:00",
        similarity_score=95.0,
    )
    return base._replace(**overrides)


@pytest.fixture
def db(tmp_path):
    from src.db.store import get_connection, init_db, insert_record

    c = get_connection(tmp_path / "notify_test.db")
    init_db(c)
    c.row_factory = sqlite3.Row

    _date = datetime(2001, 10, 1, tzinfo=timezone.utc)

    def _insert(mid):
        insert_record(c, {
            "message_id": mid, "date": _date,
            "from_address": "sender@example.com",
            "to_addresses": ["to@example.com"],
            "cc_addresses": [], "bcc_addresses": [],
            "subject": "Budget Meeting", "subject_normalized": "budget meeting",
            "body": "Body.", "source_file": "mb/1.",
            "x_from": "", "x_to": "", "x_cc": "", "x_bcc": "",
            "x_folder": "", "x_origin": "", "content_type": "",
            "has_attachment": False, "forwarded_content": "", "quoted_content": "", "headings": "",
        })

    _insert("<orig@example.com>")
    _insert("<dup@example.com>")
    _insert("<sent@example.com>")

    c.execute(
        "UPDATE emails SET is_duplicate=1, duplicate_of=?, similarity_score=95.0 WHERE message_id IN ('<dup@example.com>', '<sent@example.com>')",
        ("<orig@example.com>",),
    )
    c.execute("UPDATE emails SET notification_sent=1 WHERE message_id='<sent@example.com>'")
    c.commit()
    yield c
    c.close()


# ── load_pending_duplicates ───────────────────────────────────────────────────

def test_load_pending_excludes_already_sent(db):
    ids = [r.dup_message_id for r in load_pending_duplicates(db)]
    assert "<dup@example.com>" in ids
    assert "<sent@example.com>" not in ids


def test_load_pending_record_has_correct_fields(db):
    pending = load_pending_duplicates(db)
    rec = next(r for r in pending if r.dup_message_id == "<dup@example.com>")
    assert rec.orig_message_id == "<orig@example.com>"
    assert rec.similarity_score == pytest.approx(95.0)
    assert rec.from_address == "sender@example.com"
    assert rec.subject == "Budget Meeting"


def test_load_pending_empty_when_all_sent(db):
    db.execute("UPDATE emails SET notification_sent=1 WHERE is_duplicate=1")
    db.commit()
    assert load_pending_duplicates(db) == []


# ── mark_notification_sent ────────────────────────────────────────────────────

def test_mark_notification_sent_sets_flag(db):
    mark_notification_sent(db, "<dup@example.com>")
    db.commit()
    row = db.execute(
        "SELECT notification_sent, notification_date FROM emails WHERE message_id='<dup@example.com>'"
    ).fetchone()
    assert row["notification_sent"] == 1


def test_mark_notification_sent_records_timestamp(db):
    mark_notification_sent(db, "<dup@example.com>")
    db.commit()
    row = db.execute(
        "SELECT notification_date FROM emails WHERE message_id='<dup@example.com>'"
    ).fetchone()
    assert row["notification_date"] is not None


def test_mark_notification_sent_does_not_affect_others(db):
    mark_notification_sent(db, "<dup@example.com>")
    db.commit()
    row = db.execute(
        "SELECT notification_sent FROM emails WHERE message_id='<orig@example.com>'"
    ).fetchone()
    assert row["notification_sent"] == 0


# ── write_eml_draft ───────────────────────────────────────────────────────────

def test_write_eml_draft_creates_file(tmp_path, monkeypatch):
    import src.notify.notify as mod
    monkeypatch.setattr(mod, "REPLIES_DIR", tmp_path / "replies")

    path = write_eml_draft(dup_record(), "notifier@example.com")
    assert path.exists()
    assert path.suffix == ".eml"


def test_write_eml_draft_headers(tmp_path, monkeypatch):
    import src.notify.notify as mod
    monkeypatch.setattr(mod, "REPLIES_DIR", tmp_path / "replies")

    path = write_eml_draft(dup_record(), "notifier@example.com")
    content = path.read_text(encoding="utf-8")

    assert "From: notifier@example.com" in content
    assert "To: sender@example.com" in content
    assert "[Duplicate Notice]" in content
    assert "Budget Meeting" in content


def test_write_eml_draft_body_contains_both_ids(tmp_path, monkeypatch):
    import src.notify.notify as mod
    monkeypatch.setattr(mod, "REPLIES_DIR", tmp_path / "replies")

    rec = dup_record()
    path = write_eml_draft(rec, "notifier@example.com")
    content = path.read_text(encoding="utf-8")

    assert rec.dup_message_id in content
    assert rec.orig_message_id in content


def test_write_eml_draft_body_contains_score(tmp_path, monkeypatch):
    import src.notify.notify as mod
    monkeypatch.setattr(mod, "REPLIES_DIR", tmp_path / "replies")

    path = write_eml_draft(dup_record(similarity_score=87.3), "notifier@example.com")
    assert "87.3" in path.read_text(encoding="utf-8")


def test_write_eml_draft_unique_filename_per_message(tmp_path, monkeypatch):
    import src.notify.notify as mod
    monkeypatch.setattr(mod, "REPLIES_DIR", tmp_path / "replies")

    p1 = write_eml_draft(dup_record(dup_message_id="<aaa@x>"), "n@x.com")
    p2 = write_eml_draft(dup_record(dup_message_id="<bbb@x>"), "n@x.com")
    assert p1 != p2
