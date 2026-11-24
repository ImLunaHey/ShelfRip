-- Shelfrip community disc database (Cloudflare D1).
-- Apply with: npx wrangler d1 execute shelfrip --remote --file=schema.sql
-- then each file in migrations/ (Deploy Database.bat does both; a migration that's already in is skipped).

-- One row per disc per install: what that person filed. Filing the same disc again replaces it.
CREATE TABLE IF NOT EXISTS submissions (
  id          INTEGER PRIMARY KEY,
  disc_key    TEXT NOT NULL,     -- "h:<content hash>" (TheDiscDB-compatible fingerprint) or "s:<title signature>"
  alt_key     TEXT,              -- the signature key too, when disc_key is a hash
  install     TEXT NOT NULL,     -- salted hash of the app's random install id (never the id itself)
  created     INTEGER NOT NULL,  -- unix seconds
  app_version TEXT,
  format      TEXT,
  disc_label  TEXT,
  disc_name   TEXT,
  kind        TEXT,              -- movie | tv
  title       TEXT,
  year        TEXT,
  tmdb_id     TEXT,
  imdb_id     TEXT,
  season      INTEGER,
  titles      TEXT NOT NULL,     -- JSON list of titles, with their tracks (see worker.js: cleanTitle)
  hidden      INTEGER NOT NULL DEFAULT 0,
  accepted    INTEGER NOT NULL DEFAULT 0,  -- 1: every title filed just as our answer showed it (half a vote)
  UNIQUE (disc_key, install)
);
CREATE INDEX IF NOT EXISTS submissions_alt ON submissions(alt_key);
CREATE INDEX IF NOT EXISTS submissions_install ON submissions(install);
CREATE INDEX IF NOT EXISTS submissions_created ON submissions(created);

-- Installs an admin has blocked (their submissions are hidden and new ones refused).
CREATE TABLE IF NOT EXISTS blocked (install TEXT PRIMARY KEY, why TEXT, at INTEGER);

-- Daily counters for rate limits. key is a salted hash (install or IP), never the raw value.
CREATE TABLE IF NOT EXISTS limits (key TEXT NOT NULL, day TEXT NOT NULL, n INTEGER NOT NULL, PRIMARY KEY (key, day));

-- Answers an admin has fixed for a disc: shown instead of the vote.
CREATE TABLE IF NOT EXISTS locks (disc_key TEXT PRIMARY KEY, answer TEXT NOT NULL, at INTEGER);

-- "This disc is not <answer>": sent when someone was given a shared answer and changed it, or
-- re-matched a disc after filing. Each report counts against that answer (one per install per disc).
CREATE TABLE IF NOT EXISTS reports (
  id       INTEGER PRIMARY KEY,
  disc_key TEXT NOT NULL,
  alt_key  TEXT,
  install  TEXT NOT NULL,
  created  INTEGER NOT NULL,
  kind     TEXT,
  tmdb_id  TEXT,
  season   INTEGER,
  better   TEXT,               -- JSON {kind, title, year, tmdb_id, season}: what they filed instead
  UNIQUE (disc_key, install, kind, tmdb_id, season)
);
CREATE INDEX IF NOT EXISTS reports_alt ON reports(alt_key);

-- Feedback sent from the app's Feedback button.
CREATE TABLE IF NOT EXISTS feedback (
  id       INTEGER PRIMARY KEY,
  created  INTEGER NOT NULL,
  install  TEXT NOT NULL,      -- salted hash, as above
  kind     TEXT,               -- idea | problem | other
  title    TEXT,
  body     TEXT,
  contact  TEXT,               -- only if they chose to give an email for a reply
  app_version TEXT,
  os       TEXT,
  done     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS feedback_created ON feedback(created);
