"""
Traverse selected mailboxes, parse every email, return structured records.
Run directly to print extraction statistics.
"""

import logging
import os
from pathlib import Path
from typing import Iterator

from src.parser.parse_emails import parse_email_file

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def iter_email_files(maildir_root: Path, mailboxes: list[str]) -> Iterator[Path]:
    # os.walk used instead of rglob — handles trailing-dot filenames on Windows
    for mb in mailboxes:
        mb_path = maildir_root / mb
        if not mb_path.is_dir():
            logger.warning("Mailbox not found: %s", mb_path)
            continue
        for dirpath, _, filenames in os.walk(str(mb_path)):
            for fname in filenames:
                yield Path(dirpath) / fname


def run_ingestion(
    maildir_root: Path,
    mailboxes: list[str],
    error_log_path: Path,
) -> tuple[list[dict], list[dict]]:
    """
    Parse all emails in selected mailboxes.

    Returns:
        records   — list of successfully parsed email dicts
        failures  — list of {file, reason} dicts
    """
    error_log_path.parent.mkdir(parents=True, exist_ok=True)

    records:  list[dict] = []
    failures: list[dict] = []

    files = list(iter_email_files(maildir_root, mailboxes))
    total = len(files)
    logger.info("Found %d files across %d mailboxes", total, len(mailboxes))

    with open(error_log_path, "w", encoding="utf-8") as err_file:
        for i, fp in enumerate(files, 1):
            if i % 1000 == 0:
                logger.info("Progress: %d / %d", i, total)
            try:
                record = parse_email_file(fp, maildir_root)
                records.append(record)
            except Exception as exc:
                reason = str(exc)
                failures.append({"file": str(fp), "reason": reason})
                err_file.write(f"{fp}\t{reason}\n")

    _print_stats(records, failures, total)
    return records, failures


def _print_stats(records: list[dict], failures: list[dict], total: int) -> None:
    parsed = len(records)
    failed = len(failures)
    print(f"\n{'-'*50}")
    print(f"Total files   : {total}")
    print(f"Parsed OK     : {parsed}  ({100*parsed/max(total,1):.1f}%)")
    print(f"Failed        : {failed}  ({100*failed/max(total,1):.1f}%)")

    if not records:
        return

    # Field-level completeness
    optional_fields = [
        "cc_addresses", "bcc_addresses", "x_from", "x_to", "x_cc", "x_bcc",
        "x_folder", "x_origin", "content_type", "has_attachment",
        "forwarded_content", "quoted_content", "headings",
    ]
    print("\nOptional field completeness:")
    for field in optional_fields:
        present = sum(
            1 for r in records
            if r.get(field) not in (None, "", [], False)
        )
        print(f"  {field:<22}: {present:>6} / {parsed}  ({100*present/parsed:.1f}%)")
    print(f"{'─'*50}\n")

