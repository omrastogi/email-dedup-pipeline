import pytest
from datetime import timezone
from pathlib import Path

from src.parser.parse_emails import parse_email_file


MINIMAL_EMAIL = b"""\
Message-ID: <test-001@example.com>
Date: Mon, 01 Oct 2001 10:00:00 -0500
From: sender@example.com
To: recipient@example.com
Subject: Test Subject
X-From: Sender Name
X-Folder: INBOX

This is the email body.
"""

EMAIL_WITH_CC = b"""\
Message-ID: <test-002@example.com>
Date: Tue, 02 Oct 2001 09:00:00 -0500
From: sender@example.com
To: recipient@example.com
Cc: cc@example.com
Bcc: bcc@example.com
Subject: CC Test

Body text.
"""

EMAIL_MISSING_FROM = b"""\
Message-ID: <test-003@example.com>
Date: Mon, 01 Oct 2001 10:00:00 -0500
To: recipient@example.com
Subject: No From

Body.
"""

EMAIL_MISSING_ID = b"""\
Date: Mon, 01 Oct 2001 10:00:00 -0500
From: sender@example.com
To: recipient@example.com
Subject: No ID

Body.
"""

EMAIL_WITH_FORWARDED = b"""\
Message-ID: <test-004@example.com>
Date: Mon, 01 Oct 2001 10:00:00 -0500
From: sender@example.com
To: recipient@example.com
Subject: Fwd: Original Topic

My comments.

-----Original Message-----
From: original@example.com
Original content here.
"""


@pytest.fixture
def maildir(tmp_path):
    mb = tmp_path / "maildir" / "test-mb"
    mb.mkdir(parents=True)
    return tmp_path / "maildir"


def _write(maildir: Path, name: str, content: bytes) -> Path:
    path = maildir / "test-mb" / name
    path.write_bytes(content)
    return path


def test_parse_basic_fields(maildir):
    path = _write(maildir, "1.", MINIMAL_EMAIL)
    r = parse_email_file(path, maildir)
    assert r["message_id"] == "<test-001@example.com>"
    assert r["from_address"] == "sender@example.com"
    assert r["to_addresses"] == ["recipient@example.com"]
    assert r["subject"] == "Test Subject"
    assert "email body" in r["body"]


def test_parse_source_file_uses_forward_slashes(maildir):
    path = _write(maildir, "1.", MINIMAL_EMAIL)
    r = parse_email_file(path, maildir)
    assert r["source_file"] == "test-mb/1."
    assert "\\" not in r["source_file"]


def test_parse_subject_normalized(maildir):
    path = _write(maildir, "1.", MINIMAL_EMAIL)
    r = parse_email_file(path, maildir)
    assert r["subject_normalized"] == "Test Subject"


def test_parse_date_is_utc(maildir):
    path = _write(maildir, "1.", MINIMAL_EMAIL)
    r = parse_email_file(path, maildir)
    assert r["date"].tzinfo == timezone.utc


def test_parse_cc_bcc(maildir):
    path = _write(maildir, "2.", EMAIL_WITH_CC)
    r = parse_email_file(path, maildir)
    assert "cc@example.com" in r["cc_addresses"]
    assert "bcc@example.com" in r["bcc_addresses"]


def test_parse_missing_from_raises(maildir):
    path = _write(maildir, "3.", EMAIL_MISSING_FROM)
    with pytest.raises(ValueError, match="From"):
        parse_email_file(path, maildir)


def test_parse_missing_message_id_raises(maildir):
    path = _write(maildir, "5.", EMAIL_MISSING_ID)
    with pytest.raises(ValueError, match="Message-ID"):
        parse_email_file(path, maildir)


def test_parse_forwarded_content_split(maildir):
    path = _write(maildir, "4.", EMAIL_WITH_FORWARDED)
    r = parse_email_file(path, maildir)
    assert "Original Message" in r["forwarded_content"]
    assert "My comments" in r["body"]
    assert "Original content" not in r["body"]
