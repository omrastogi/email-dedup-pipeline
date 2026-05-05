## What I am measuring
- 1. What, 2. why, 3. how and challenges, 4. edge-cases, 5. improvements

### Parsing and Ingestion
1. Used `email` library to extract structured info from raw email files. Walks the maildir and dumps dicts.
2. Convert raw text to structured data so I can put it in a DB and query it.
3. Problems solved: 1. Non-standard timezones (PST/EST/etc patched to numeric offsets) 2. Splitting original vs forwarded vs quoted body 3. Windows path issues with trailing dots 4. Subject normalization for Re:/Fwd:
4. Edge cases: HTML-only emails come back empty. Encoded headers (`=?UTF-8?B?...`) not fully decoded. Heading regex is hacky, catches signatures.
5. Improvements: switch policy from compat32 to default for header decoding. Add HTML fallback. Parallelize ingestion.

### Database
1. SQLite with `emails` table + `email_recipients` join table. `INSERT OR IGNORE` on message_id.
2. Need somewhere to put the parsed data. Spec wanted normalized recipients, not CSV strings.
3. WAL mode + synchronous=NORMAL for faster bulk inserts. Dates stored as ISO strings so they sort right. `has_attachment` cast to int because SQLite has no bool.
4. Edge cases: message_id collisions across mailboxes are silently skipped. No batched transactions so a crash mid-run loses progress. FK has to be enabled per connection.
5. Improvements: batch commits every 1000 rows. Track collision count somewhere. Index subject_normalized.

### Deduplication
1. Bucket by (sender, normalized subject), fuzzy match bodies in each bucket with rapidfuzz, cluster with Union-Find, mark earliest as original.
2. Comparing all 22k emails pairwise is 484M ops. Bucketing kills most of that since duplicates have to share sender+subject anyway.
3. token_sort_ratio handles word reordering. MIN_BODY_LEN=20 avoids matching empty bodies. Confirmation pass against the original to avoid transitive chain false positives (A~B~C but A!~C).
4. Edge cases: subject typos break bucketing. Empty bodies skip comparison. Big buckets are still quadratic. Threshold hardcoded at 90.
5. Improvements: expose threshold as CLI flag. Pre-cluster subjects with edit distance to catch typos. Vectorize with rapidfuzz.process.cdist.

### Notifications (MCP)
1. Custom Gmail MCP server (stdio transport, SMTP+App Password) exposing a `send_email` tool. Pipeline reads flagged duplicates from DB, builds notification text from the spec template, writes `.eml` drafts in dry-run, sends via the MCP server in `--send-live` mode. Logs every attempt to `output/send_log.csv` and marks `notification_sent=1` on success.
2. Spec required MCP integration with a Gmail-compatible server. Built my own instead of pulling a third-party server because App Password + SMTP is simpler than OAuth and gives me full control over the tool surface.
3. Dry-run by default so I can iterate without spamming. `.env` for creds (gitignored), `mcp_config.json.example` for the public template. asyncio.run per email since the MCP client is async-only. References header set to the duplicate's message_id so threading works in Gmail.
4. Edge cases: send-to-self for the demo (Enron addresses are dead, so notifications go to my own inbox). No retry on SMTP failure, the run just logs and moves on. Filename sanitization for .eml files (strip `<>`, replace slashes, truncate to 80 chars) since Message-IDs have weird chars. App Password is 16 chars, no spaces, easy to mistype. Spawning a new MCP subprocess per email is slow but fine at the spec's scale.
5. Improvements: batch sends in one MCP session instead of one-shot connections. Add retry with backoff. Support real OAuth for production. Send to original recipient when not in demo mode. Rate-limit to avoid Gmail's 500/day cap.