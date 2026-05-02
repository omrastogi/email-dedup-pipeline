"""
SQLite ingestion layer.
Creates schema, inserts parsed email records, handles duplicates via INSERT OR IGNORE.
"""

import sqlite3
from pathlib import Path

DB_PATH     = Path(__file__).parents[2] / "data" / "enron.db"
SCHEMA_PATH = Path(__file__).parents[2] / "schema.sql"


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()


def insert_record(conn: sqlite3.Connection, record: dict) -> bool:
    """
    Insert one parsed email record.
    Returns True if inserted, False if message_id already exists (skipped).
    """
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO emails (
            message_id, date, from_address, subject, subject_normalized,
            body, source_file, x_from, x_to, x_cc, x_bcc,
            x_folder, x_origin, content_type, has_attachment,
            forwarded_content, quoted_content, headings
        ) VALUES (
            :message_id, :date_str, :from_address, :subject, :subject_normalized,
            :body, :source_file, :x_from, :x_to, :x_cc, :x_bcc,
            :x_folder, :x_origin, :content_type, :has_attachment,
            :forwarded_content, :quoted_content, :headings
        )
        """,
        {
            **record,
            "date_str":      record["date"].isoformat() if record.get("date") else None,
            "has_attachment": 1 if record.get("has_attachment") else 0,
        },
    )
    inserted = cur.rowcount == 1

    if inserted:
        for field in ("to", "cc", "bcc"):
            addrs = record.get(f"{field}_addresses") or []
            for addr in addrs:
                conn.execute(
                    "INSERT INTO email_recipients (message_id, field, address) VALUES (?,?,?)",
                    (record["message_id"], field, addr),
                )
    return inserted


def bulk_insert(conn: sqlite3.Connection, records: list[dict]) -> tuple[int, int]:
    """Insert a list of records. Returns (inserted, skipped)."""
    inserted = skipped = 0
    for rec in records:
        if insert_record(conn, rec):
            inserted += 1
        else:
            skipped += 1
    conn.commit()
    return inserted, skipped
