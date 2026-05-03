"""
Notification sender for flagged duplicate emails.

Dry-run (default): writes .eml draft files to output/replies/.
Live mode (--send-live / send_live=True): sends via Gmail MCP server.
"""

import asyncio
import csv
import logging
import os
import sqlite3
from datetime import datetime, timezone
from email.mime.text import MIMEText
from pathlib import Path
from typing import NamedTuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger(__name__)

ROOT        = Path(__file__).parents[2]
DB_PATH     = ROOT / "data" / "enron.db"
REPLIES_DIR = ROOT / "output" / "replies"
SEND_LOG    = ROOT / "output" / "send_log.csv"
MCP_SERVER  = ROOT / "src" / "notify" / "gmail_mcp_server.py"

NOTIFICATION_TEMPLATE = """\
This is an automated notification from the Email Deduplication System.

Your email has been identified as a potential duplicate:

Your Email (Flagged):
  Message-ID : {dup_message_id}
  Date Sent  : {dup_date}
  Subject    : {subject}

Original Email on Record:
  Message-ID : {orig_message_id}
  Date Sent  : {orig_date}

Similarity Score: {similarity_score:.1f}%

If this was NOT a duplicate and you intended to send this email, please reply
with CONFIRM to restore it to active status.
No action is required if this is indeed a duplicate.
"""


class DuplicateRecord(NamedTuple):
    dup_message_id:  str
    orig_message_id: str
    subject:         str
    from_address:    str
    dup_date:        str
    orig_date:       str
    similarity_score: float


# ── DB helpers ────────────────────────────────────────────────────────────────

def load_pending_duplicates(conn: sqlite3.Connection) -> list[DuplicateRecord]:
    """Return flagged duplicates that haven't had a notification sent yet."""
    rows = conn.execute("""
        SELECT
            d.message_id   AS dup_message_id,
            d.duplicate_of AS orig_message_id,
            d.subject,
            d.from_address,
            d.date         AS dup_date,
            o.date         AS orig_date,
            d.similarity_score
        FROM emails d
        JOIN emails o ON d.duplicate_of = o.message_id
        WHERE d.is_duplicate = 1
          AND d.notification_sent = 0
        ORDER BY d.from_address, d.date
    """).fetchall()
    return [DuplicateRecord(**dict(r)) for r in rows]


def mark_notification_sent(conn: sqlite3.Connection, message_id: str) -> None:
    conn.execute(
        "UPDATE emails SET notification_sent=1, notification_date=? WHERE message_id=?",
        (datetime.now(timezone.utc).isoformat(), message_id),
    )


# ── .eml draft writer ─────────────────────────────────────────────────────────

def write_eml_draft(rec: DuplicateRecord, sender_address: str) -> Path:
    REPLIES_DIR.mkdir(parents=True, exist_ok=True)

    body = NOTIFICATION_TEMPLATE.format(
        dup_message_id=rec.dup_message_id,
        dup_date=rec.dup_date,
        subject=rec.subject,
        orig_message_id=rec.orig_message_id,
        orig_date=rec.orig_date,
        similarity_score=rec.similarity_score,
    )

    msg = MIMEText(body, "plain")
    msg["From"]       = sender_address
    msg["To"]         = rec.from_address
    msg["Subject"]    = f"[Duplicate Notice] Re: {rec.subject}"
    msg["Date"]       = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    msg["References"] = rec.dup_message_id

    # Sanitize message_id for use as filename
    safe_id = rec.dup_message_id.strip("<>").replace("/", "_").replace("\\", "_")[:80]
    eml_path = REPLIES_DIR / f"{safe_id}.eml"
    eml_path.write_text(msg.as_string(), encoding="utf-8")
    return eml_path


# ── MCP live send ─────────────────────────────────────────────────────────────

async def _send_via_mcp(rec: DuplicateRecord, sender_address: str) -> tuple[bool, str]:
    """Send one notification email via the Gmail MCP server. Returns (success, status)."""
    body = NOTIFICATION_TEMPLATE.format(
        dup_message_id=rec.dup_message_id,
        dup_date=rec.dup_date,
        subject=rec.subject,
        orig_message_id=rec.orig_message_id,
        orig_date=rec.orig_date,
        similarity_score=rec.similarity_score,
    )

    server_params = StdioServerParameters(
        command="python",
        args=[str(MCP_SERVER)],
        env={**os.environ},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool(
                "send_email",
                arguments={
                    "to":         sender_address,   # send to own account for demo
                    "subject":    f"[Duplicate Notice] Re: {rec.subject}",
                    "body":       body,
                    "references": rec.dup_message_id,
                },
            )
    status = result.content[0].text if result.content else "no response"
    success = status.startswith("OK")
    return success, status


# ── Entry point ───────────────────────────────────────────────────────────────

def run_notifications(
    send_live: bool = False,
    limit: int = 50,
    db_path: Path = DB_PATH,
) -> None:
    """
    Process pending duplicate notifications.

    Args:
        send_live: If True, actually send via Gmail MCP. Otherwise write .eml drafts only.
        limit:     Max notifications to process in one run (avoids flooding).
    """
    sender_address = os.environ.get("GMAIL_ADDRESS", "your.email@gmail.com")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    pending = load_pending_duplicates(conn)
    logger.info("Pending notifications: %d (limit=%d)", len(pending), limit)
    pending = pending[:limit]

    SEND_LOG.parent.mkdir(parents=True, exist_ok=True)
    log_exists = SEND_LOG.exists()

    with open(SEND_LOG, "a", newline="", encoding="utf-8") as logf:
        writer = csv.DictWriter(logf, fieldnames=[
            "timestamp", "delivered_to", "original_sender", "subject", "message_id", "status", "error",
        ])
        if not log_exists:
            writer.writeheader()

        sent = skipped = errors = 0
        for rec in pending:
            subject_line = f"[Duplicate Notice] Re: {rec.subject}"
            timestamp    = datetime.now(timezone.utc).isoformat()

            if not send_live:
                eml = write_eml_draft(rec, sender_address)
                writer.writerow({
                    "timestamp":       timestamp,
                    "delivered_to":    sender_address,
                    "original_sender": rec.from_address,
                    "subject":         subject_line,
                    "message_id":      rec.dup_message_id,
                    "status":          "dry-run",
                    "error":           "",
                })
                skipped += 1
                continue

            # Live send
            try:
                success, status = asyncio.run(_send_via_mcp(rec, sender_address))
                if success:
                    mark_notification_sent(conn, rec.dup_message_id)
                    sent += 1
                else:
                    errors += 1
                writer.writerow({
                    "timestamp":       timestamp,
                    "delivered_to":    sender_address,
                    "original_sender": rec.from_address,
                    "subject":         subject_line,
                    "message_id":      rec.dup_message_id,
                    "status":          "sent" if success else "error",
                    "error":           "" if success else status,
                })
            except Exception as exc:
                errors += 1
                writer.writerow({
                    "timestamp":       timestamp,
                    "delivered_to":    sender_address,
                    "original_sender": rec.from_address,
                    "subject":         subject_line,
                    "message_id":      rec.dup_message_id,
                    "status":          "error",
                    "error":      str(exc),
                })

    conn.commit()
    conn.close()

    mode = "LIVE" if send_live else "DRY-RUN"
    print(f"\n{'-'*52}")
    print(f"Mode          : {mode}")
    print(f"Processed     : {len(pending)}")
    if send_live:
        print(f"Sent          : {sent}")
        print(f"Errors        : {errors}")
    else:
        print(f"Drafts written: {skipped}  ->  {REPLIES_DIR}")
    print(f"Log           : {SEND_LOG}")
    print(f"{'-'*52}\n")


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%H:%M:%S")
    p = argparse.ArgumentParser()
    p.add_argument("--send-live", action="store_true")
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args()
    run_notifications(send_live=args.send_live, limit=args.limit)
