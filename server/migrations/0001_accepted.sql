-- 2026-11: weighted votes. 1 when every title was filed just as the database's answer showed it,
-- which counts as half a vote (see worker.js: ACCEPTED_WEIGHT). Older rows count fully, as before.
-- Tracks and per-title "accepted" flags live inside the titles JSON, so they need no column.
ALTER TABLE submissions ADD COLUMN accepted INTEGER NOT NULL DEFAULT 0;
