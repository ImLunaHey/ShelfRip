-- Shelfrip community disc database (Cloudflare D1).
-- Apply with: npx wrangler d1 execute shelfrip --remote --file=schema.sql

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
  titles      TEXT NOT NULL,     -- JSON list of titles (see worker.js: cleanTitle)
  hidden      INTEGER NOT NULL DEFAULT 0,
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
