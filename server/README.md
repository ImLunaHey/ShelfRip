# Shelfrip disc database (server)

A small Cloudflare Worker with a D1 (SQLite) database. Every Shelfrip install that has sharing
turned on sends what it filed for each disc; every install asks it first when a disc is ripped.
It runs on Cloudflare's free tier (100,000 requests a day), so it costs nothing at this scale.

## Deploy (Windows)

1. Install [Node.js LTS](https://nodejs.org/) (or `winget install OpenJS.NodeJS.LTS`).
2. Make a free [Cloudflare account](https://dash.cloudflare.com/sign-up).
3. Double-click **Deploy Database.bat** in this folder. A browser window asks you to allow Wrangler
   (Cloudflare's tool) the first time. It creates the database, deploys, and prints the address,
   something like `https://shelfrip-db.<your-name>.workers.dev`.
4. Put that address in `COMMUNITY_URL` in `paths.py` and release a new version.

`.secrets.json` (created by the deploy, never committed) holds the `SALT` that hashes install ids and
the `ADMIN_TOKEN` for the admin calls. Keep it: a new SALT makes every install look new.

## API

| Call | What it does |
|---|---|
| `POST /v1/submit` | One filed disc: `{install_id, app_version, disc: {content_hash, signature, format, label, name}, media: {kind, title, year, tmdb_id, imdb_id, season}, titles: [...]}` |
| `POST /v1/report` | "This disc is not that": `{install_id, disc: {content_hash, signature}, wrong: {kind, tmdb_id, season}, instead: {...}}`. Sent when someone was given a shared answer and filed or re-matched the disc as something else |
| `POST /v1/feedback` | A message from the app's Feedback button: `{install_id, kind, title, body, contact, app_version, os}` (20 a day per install) |
| `GET /v1/disc?h=<content hash>&s=<signature>` | The agreed answer for a disc, title by title, with vote counts |
| `GET /v1/export` | Every disc's agreed answer as one JSON file (CC0) |
| `GET /v1/stats` | How many discs, submissions and installs |
| `GET /v1/admin/recent?limit=50` | Latest submissions (header `Authorization: Bearer <ADMIN_TOKEN>`) |
| `POST /v1/admin/block` `{install, why}` | Hide everything from one install (first 12 characters of its id as shown in `recent`) |
| `POST /v1/admin/hide` `{id, hidden}` | Hide or show one submission |
| `POST /v1/admin/lock` `{disc_key, answer}` | Fix a disc's answer by hand (`answer: null` removes the lock) |
| `GET /v1/admin/reports` | Discs people said were wrong, with what they filed instead and the current answer |
| `GET /v1/admin/feedback` | Feedback, newest first (`?all=1` includes ones marked done) |
| `POST /v1/admin/feedback` `{id, done}` | Mark feedback done |

On the PC that deployed the database (the one with `.secrets.json`), Shelfrip shows the feedback
and the reports in Settings > Shelfrip.

## How answers are decided

- A disc is found by its content hash (the same fingerprint TheDiscDB uses), or failing that by a
  signature of its titles' lengths and sizes.
- What the disc *is* (movie or show, TMDB id, season) is whatever most installs said, less one for
  each other install that reported it as wrong. If the reports cancel out every vote, the disc has
  no answer (the app falls back to its other sources) until someone files it again.
- Among those, each title (matched by playlist and length) gets the answer most installs gave:
  the movie, an episode number, an extra's category and name, or "skipped".
- An answer counts as confirmed once two separate installs agree (after reports) and nobody outvotes them. The app
  still uses an unconfirmed answer, but warns on the review page and doesn't file the disc on its own.
- Each install counts once per disc (filing the same disc again replaces your earlier submission).
  Rate limits: 200 submissions a day per install, 400 per IP.

## Privacy

Stored per submission: the disc's fingerprint, label and name as printed on the disc, its format,
what it was identified as, and per title the playlist, length, size, chapter count and the name and
category chosen. Install ids and IP addresses are only kept as salted hashes; IPs only inside daily
rate-limit counters. No file paths, folder names, library details, keys or personal names.

## Local testing

```
npm install wrangler@4
echo SALT=test> .dev.vars & echo ADMIN_TOKEN=test>> .dev.vars
npx wrangler d1 execute shelfrip --local --file=schema.sql
npx wrangler dev --local
```
then set `"community_url": "http://localhost:8787"` in Shelfrip's config.json.
