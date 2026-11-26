-- 2026-11: a problem report can carry the latest rips' logs (MakeMKV's title list and rip log),
-- gzip-compressed and base64-encoded. NULL when none were sent.
ALTER TABLE feedback ADD COLUMN logs TEXT;
