-- Enron Email Pipeline — Sample Queries
-- Run against: data/enron.db (SQLite)

-- ─────────────────────────────────────────────────────────────────────────────
-- Query 1: Top 10 senders by email volume
-- Expected: pete.davis, scott.neal, enron bulk senders near top
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    from_address,
    COUNT(*)                                          AS total_emails,
    SUM(is_duplicate)                                 AS duplicates,
    ROUND(100.0 * SUM(is_duplicate) / COUNT(*), 1)   AS duplicate_pct
FROM emails
GROUP BY from_address
ORDER BY total_emails DESC
LIMIT 10;


-- ─────────────────────────────────────────────────────────────────────────────
-- Query 2: Emails received in a date range (2001-10-01 to 2001-10-31)
-- Expected: Enron collapse period — heavy traffic
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    DATE(date)   AS day,
    COUNT(*)     AS emails_received
FROM emails
WHERE date >= '2001-10-01'
  AND date <  '2001-11-01'
GROUP BY day
ORDER BY day;


-- ─────────────────────────────────────────────────────────────────────────────
-- Query 3: All emails with CC recipients (join to normalized table)
-- Expected: ~6445 emails with at least one CC address
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    e.message_id,
    e.date,
    e.from_address,
    e.subject,
    r.address AS cc_address
FROM emails e
JOIN email_recipients r ON e.message_id = r.message_id
WHERE r.field = 'cc'
ORDER BY e.date DESC
LIMIT 20;


-- ─────────────────────────────────────────────────────────────────────────────
-- Query 4: Duplicate groups with the most members
-- Expected: Schedule Crawler alerts, newsletters at top
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    o.message_id                         AS original_message_id,
    o.from_address,
    o.subject,
    o.date                               AS original_date,
    COUNT(d.message_id)                  AS duplicate_count,
    ROUND(AVG(d.similarity_score), 1)    AS avg_similarity
FROM emails o
JOIN emails d ON d.duplicate_of = o.message_id
GROUP BY o.message_id
ORDER BY duplicate_count DESC
LIMIT 10;


-- ─────────────────────────────────────────────────────────────────────────────
-- Query 5: Notification status summary
-- Expected: notification_sent=0 for all (dry-run only so far)
-- ─────────────────────────────────────────────────────────────────────────────
SELECT
    notification_sent,
    COUNT(*) AS count
FROM emails
WHERE is_duplicate = 1
GROUP BY notification_sent;
