-- Query 1: Count emails per sender (top 10)
SELECT u.email, u.display_name, COUNT(e.message_id) AS email_count
FROM emails e
JOIN users u ON e.from_user_id = u.user_id
GROUP BY e.from_user_id
ORDER BY email_count DESC
LIMIT 10;

-- Query 2: Find all emails in a date range
SELECT e.message_id, e.date, u.email AS sender, e.subject
FROM emails e
JOIN users u ON e.from_user_id = u.user_id
WHERE e.date BETWEEN '2001-01-01T00:00:00+00:00' AND '2001-12-31T23:59:59+00:00'
ORDER BY e.date;

-- Query 3: Find emails that have CC recipients with count
SELECT e.message_id, e.date, u.email AS sender, e.subject,
       COUNT(r.id) AS cc_count
FROM emails e
JOIN users u ON e.from_user_id = u.user_id
JOIN email_recipients r ON e.message_id = r.message_id AND r.type = 'cc'
GROUP BY e.message_id
ORDER BY cc_count DESC
LIMIT 20;
