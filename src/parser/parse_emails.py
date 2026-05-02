"""
Email parser for the Enron maildir dataset.
Extracts mandatory and optional fields from raw RFC 2822 files.
"""

import email
import email.policy
import re
import logging
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime, getaddresses
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Timezone abbreviation → UTC offset (seconds). Covers common US tz names in the dataset.
_TZ_OFFSETS = {
    "PST": -28800, "PDT": -25200,
    "MST": -25200, "MDT": -21600,
    "CST": -21600, "CDT": -18000,
    "EST": -18200, "EDT": -14400,
}

_QUOTE_RE = re.compile(r"^>+.*$", re.MULTILINE)
_FWD_RE   = re.compile(
    r"(-{3,}[ \t]*(?:original|forwarded)[ \t]*message[ \t]*-{3,}.*)",
    re.IGNORECASE | re.DOTALL,
)
_SUBJECT_PREFIX_RE = re.compile(r"^(re|fwd?|fw):\s*", re.IGNORECASE)


def _normalize_subject(subject: str) -> str:
    """Strip Re:/Fwd: prefixes recursively for comparison."""
    while True:
        stripped = _SUBJECT_PREFIX_RE.sub("", subject).strip()
        if stripped == subject:
            return subject
        subject = stripped


def _parse_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    # Patch unknown tz abbreviations before handing off to stdlib
    for abbr, offset_sec in _TZ_OFFSETS.items():
        if abbr in date_str:
            sign = "+" if offset_sec >= 0 else "-"
            h, m = divmod(abs(offset_sec) // 60, 60)
            date_str = date_str.replace(f"({abbr})", "").replace(abbr, f"{sign}{h:02d}{m:02d}")
            break
    try:
        dt = parsedate_to_datetime(date_str)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _extract_addresses(header_value: str) -> list[str]:
    """Return list of bare email addresses from a header value."""
    if not header_value:
        return []
    pairs = getaddresses([header_value])
    return [addr.lower().strip() for _, addr in pairs if addr.strip()]


def _split_body(raw_body: str) -> tuple[str, str, str]:
    """Return (clean_body, forwarded_content, quoted_content)."""
    fwd_match = _FWD_RE.search(raw_body)
    if fwd_match:
        forwarded = fwd_match.group(1).strip()
        raw_body  = raw_body[: fwd_match.start()].strip()
    else:
        forwarded = ""

    quoted_lines = _QUOTE_RE.findall(raw_body)
    quoted       = "\n".join(quoted_lines).strip()
    clean        = _QUOTE_RE.sub("", raw_body).strip()

    return clean, forwarded, quoted


def _get_text_body(msg: email.message.Message) -> str:
    """Walk MIME parts and return first text/plain payload."""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
        raw = msg.get_payload()
        return raw if isinstance(raw, str) else ""


def _infer_has_attachment(msg: email.message.Message, body: str) -> bool:
    if msg.is_multipart():
        for part in msg.walk():
            disp = part.get("Content-Disposition", "")
            if "attachment" in disp.lower():
                return True
    patterns = [r"\battachment\b", r"<embedded", r"\.(?:xls|doc|pdf|zip|ppt)\b"]
    for p in patterns:
        if re.search(p, body, re.IGNORECASE):
            return True
    return False


def parse_email_file(file_path: Path, maildir_root: Path) -> dict:
    """
    Parse a single email file.

    Returns a dict with all mandatory + optional fields.
    Raises ValueError with a human-readable reason if a mandatory field is missing.
    """
    # \\?\ prefix disables Windows path normalization (needed for trailing-dot filenames)
    win_path = r"\\?\\" + str(file_path.resolve())
    with open(win_path, "rb") as fh:
        raw = fh.read()
    try:
        msg = email.message_from_bytes(raw, policy=email.policy.compat32)
    except Exception as exc:
        raise ValueError(f"email.message_from_bytes failed: {exc}") from exc

    # ── Mandatory fields ────────────────────────────────────────────────────
    message_id = (msg.get("Message-ID") or "").strip()
    if not message_id:
        raise ValueError("missing Message-ID")

    date_raw = msg.get("Date") or ""
    date     = _parse_date(date_raw)
    if date is None:
        raise ValueError(f"unparseable Date: {date_raw!r}")

    from_raw     = msg.get("From") or ""
    from_addrs   = _extract_addresses(from_raw)
    from_address = from_addrs[0] if from_addrs else None
    if not from_address:
        raise ValueError("missing From address")

    to_raw       = msg.get("To") or ""
    to_addresses = _extract_addresses(to_raw)
    if not to_addresses:
        raise ValueError("empty To field")

    subject = (msg.get("Subject") or "").strip()

    raw_body              = _get_text_body(msg)
    body, forwarded, quoted = _split_body(raw_body)

    source_file = str(file_path.relative_to(maildir_root)).replace("\\", "/")

    # ── Optional fields ─────────────────────────────────────────────────────
    cc_addresses  = _extract_addresses(msg.get("Cc")  or "")
    bcc_addresses = _extract_addresses(msg.get("Bcc") or "")

    x_from   = (msg.get("X-From")   or "").strip()
    x_to     = (msg.get("X-To")     or "").strip()
    x_cc     = (msg.get("X-cc")     or "").strip()
    x_bcc    = (msg.get("X-bcc")    or "").strip()
    x_folder = (msg.get("X-Folder") or "").strip()
    x_origin = (msg.get("X-Origin") or "").strip()

    content_type   = (msg.get("Content-Type") or "").strip()
    has_attachment = _infer_has_attachment(msg, raw_body)

    # Headings: lines that look like a title (ALL CAPS or Title Case, short, no end punctuation)
    heading_re = re.compile(r"^[A-Z][A-Za-z0-9 ,&'\-]{2,60}$")
    headings = [l.strip() for l in body.splitlines()
                if heading_re.match(l.strip()) and len(l.strip().split()) <= 8]

    return {
        # mandatory
        "message_id":        message_id,
        "date":              date,
        "from_address":      from_address,
        "to_addresses":      to_addresses,
        "subject":           subject,
        "subject_normalized": _normalize_subject(subject),
        "body":              body,
        "source_file":       source_file,
        # optional
        "cc_addresses":      cc_addresses,
        "bcc_addresses":     bcc_addresses,
        "x_from":            x_from,
        "x_to":              x_to,
        "x_cc":              x_cc,
        "x_bcc":             x_bcc,
        "x_folder":          x_folder,
        "x_origin":          x_origin,
        "content_type":      content_type,
        "has_attachment":    has_attachment,
        "forwarded_content": forwarded,
        "quoted_content":    quoted,
        "headings":          "; ".join(headings),
    }
