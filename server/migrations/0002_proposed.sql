-- 2026-11: what Shelfrip suggested before the person reviewed it, to tell Shelfrip's wrong guesses
-- from people's edits. {} when they kept Shelfrip's match, else the match it suggested; NULL for apps
-- before this. Per-title "changed" flags live inside the titles JSON, so they need no column.
ALTER TABLE submissions ADD COLUMN proposed TEXT;
