-- 2026-11: recent app logs sent with "Something's wrong" and "Other" feedback (the person can untick
-- them). Shelfrip removes the Windows user name, home folder and keys before sending. NULL = none sent.
ALTER TABLE feedback ADD COLUMN logs TEXT;
