"""
Enron Email Pipeline — main entry point.

Usage:
    python main.py               # parse + ingest (dry-run for notifications)
    python main.py --send-live   # also send notification emails via MCP
"""

import argparse
import logging
from pathlib import Path

import autoroot  # adds project root to sys.path
import autorootcwd
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

ROOT = Path(__file__).parent

from src.parser.parse_emails import parse_email_file
from src.parser.ingest import iter_email_files
from src.db.store import get_connection, init_db, insert_record

MAILDIR_ROOT       = ROOT / "data" / "maildir"
SELECTED_MAILBOXES = ["guzman-m", "lay-k", "hain-m", "blair-l", "neal-s"]
ERROR_LOG_PATH     = ROOT / "logs" / "error_log.txt"
BATCH_SIZE         = 500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run_pipeline(send_live: bool = False, ingest_only: bool = False) -> None:
    ERROR_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection()
    init_db(conn)

    total = inserted = skipped = failed = 0
    field_counts: dict[str, int] = {}

    optional_fields = [
        "cc_addresses", "bcc_addresses", "forwarded_content",
        "quoted_content", "headings", "has_attachment",
    ]

    with open(ERROR_LOG_PATH, "w", encoding="utf-8") as err_file:
        for fp in iter_email_files(MAILDIR_ROOT, SELECTED_MAILBOXES):
            total += 1
            try:
                record = parse_email_file(fp, MAILDIR_ROOT)
                if insert_record(conn, record):
                    inserted += 1
                    for f in optional_fields:
                        v = record.get(f)
                        if v not in (None, "", [], False, 0):
                            field_counts[f] = field_counts.get(f, 0) + 1
                else:
                    skipped += 1
            except Exception as exc:
                failed += 1
                err_file.write(f"{fp}\t{exc}\n")

            if total % 1000 == 0:
                conn.commit()
                logger.info("Progress: %d  inserted=%d  skipped=%d  failed=%d",
                            total, inserted, skipped, failed)

    conn.commit()
    conn.close()

    print(f"\n{'-'*52}")
    print(f"Total files   : {total}")
    print(f"Inserted      : {inserted}")
    print(f"Skipped (dup) : {skipped}")
    print(f"Failed        : {failed}")
    print(f"\nOptional field completeness (of inserted):")
    for f in optional_fields:
        n = field_counts.get(f, 0)
        pct = 100 * n / max(inserted, 1)
        print(f"  {f:<24}: {n:>6}  ({pct:.1f}%)")
    print(f"{'-'*52}\n")

    if ingest_only:
        return

    logger.info("Running deduplication...")
    _run_dedupe_and_notify(send_live=send_live)
    if not send_live:
        logger.info("Notifications dry-run complete. Use --send-live to actually send.")


def _run_dedupe_and_notify(send_live: bool) -> None:
    from src.dedupe.dedupe import run_deduplication
    run_deduplication()
    from src.notify.notify import run_notifications
    run_notifications(send_live=send_live)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Enron Email Pipeline")
    parser.add_argument("--send-live", action="store_true",
                        help="Send notification emails via Gmail MCP")
    parser.add_argument("--ingest-only", action="store_true",
                        help="Parse and store emails, then stop (skip dedupe and notify)")
    parser.add_argument("--dedupe-only", action="store_true",
                        help="Run deduplication on an already-populated DB, then stop")
    args = parser.parse_args()

    if args.dedupe_only:
        _run_dedupe_and_notify(send_live=False)
    else:
        run_pipeline(send_live=args.send_live, ingest_only=args.ingest_only)
