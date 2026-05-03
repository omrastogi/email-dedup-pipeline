import os
from pathlib import Path
from parse_emails import parse_email_file

maildir = Path("../../data/maildir")
_all = []
for dirpath, _, fnames in os.walk(str(maildir / "lay-k" / "sent_items")):
    for fn in fnames:
        _all.append(Path(dirpath) / fn)
test_files = _all[:5]

for f in test_files:
    try:
        r = parse_email_file(f, maildir)
        print(f"OK  {f.name}: from={r['from_address']}  date={r['date']}  subj={r['subject'][:60]!r}")
        print(f"    to={r['to_addresses'][:2]}  has_attach={r['has_attachment']}")
        print(f"    body_len={len(r['body'])}  fwd_len={len(r['forwarded_content'])}  quoted_len={len(r['quoted_content'])}")
    except Exception as e:
        print(f"ERR {f.name}: {e}")
    print()
