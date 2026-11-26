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

Running **Deploy Database.bat** again later is how updates go out: it re-applies `schema.sql`, applies
anything new in `migrations/` (ones already in are skipped), then deploys the new `worker.js`.

`.secrets.json` (created by the deploy, never committed) holds the `SALT` that hashes install ids,
the `ADMIN_TOKEN` for the admin calls and the shared `TMDB_KEY` (asked for once during the deploy;
press Enter to leave it out, and delete the `TMDB_KEY` line to be asked again). Keep it: a new SALT makes every install look new.

## API

| Call | What it does |
|---|---|
| `POST /v1/submit` | One filed disc: `{install_id, app_version, disc: {content_hash, signature, format, label, name}, media: {kind, title, year, tmdb_id, imdb_id, season}, titles: [...]}`. Each title may carry `tracks: {video: {codec, res}, audio: [{lang, codec, ch, commentary, name, core}], subs: [{lang, forced}]}` (up to 24 audio and 48 subtitle tracks) and `accepted: true` when it was filed exactly as this database's answer showed it, and `changed: true` when the person changed what Shelfrip suggested for it. `proposed` (optional): `{known: true}` when they kept Shelfrip's match, or the `{kind, title, year, tmdb_id, season}` Shelfrip suggested when they picked another |
| `POST /v1/report` | "This disc is not that": `{install_id, disc: {content_hash, signature}, wrong: {kind, tmdb_id, season}, instead: {...}}`. Sent when someone was given a shared answer and filed or re-matched the disc as something else |
| `POST /v1/feedback` | A message from the app's Feedback button: `{install_id, kind, title, body, contact, app_version, os, logs?}` (20 a day per install; `logs` = the latest rips' logs, gzip + base64, up to 1.4 MB) |
| `GET /v1/disc?h=<content hash>&s=<signature>` | The agreed answer for a disc, title by title, with vote counts (`votes`: installs, `weight`: weighted votes), the tracks most people saw, and a `confidence` from 0 to 100 for the disc and each title |
| `GET /v1/export` | Every disc's agreed answer as one JSON file (CC0) |
| `GET /v1/stats` | How many discs, submissions and installs |
| `GET /v1/tmdb/<path>?...` | TMDB's API with Shelfrip's shared key (`TMDB_KEY` secret), for installs without a key of their own. Only the calls the app makes (`search/movie`, `search/tv`, `movie/<id>`, `tv/<id>`, `tv/<id>/season/<n>`, credits, external ids, `configuration`) and their usual parameters are passed on. Answers are cached for a day at Cloudflare, shared by everyone; misses are limited to 3,000 a day per IP. 503 when no key is set |
| `GET /v1/admin/recent?limit=50` | Latest submissions (header `Authorization: Bearer <ADMIN_TOKEN>`) |
| `POST /v1/admin/block` `{install, why}` | Hide everything from one install (first 12 characters of its id as shown in `recent`) |
| `POST /v1/admin/hide` `{id, hidden}` | Hide or show one submission |
| `POST /v1/admin/lock` `{disc_key, answer}` | Fix a disc's answer by hand (`answer: null` removes the lock) |
| `GET /v1/admin/reports` | Discs people said were wrong, with what they filed instead and the current answer |
| `GET /v1/admin/feedback` | Feedback, newest first (`?all=1` includes ones marked done) |
| `GET /v1/admin/feedback/logs?id=N` | The logs one report carried (gzip + base64); the list shows `logs_size` |
| `POST /v1/admin/feedback` `{id, done}` | Mark feedback done |

On the PC that deployed the database (the one with `.secrets.json`), Shelfrip shows the feedback
and the reports in Settings > Shelfrip.

## How answers are decided

- A disc is found by its content hash (the same fingerprint TheDiscDB uses), or failing that by a
  signature of its titles' lengths and sizes.
- What the disc *is* (movie or show, TMDB id, season) is whatever most installs said, less one for
  each other install that reported it as wrong. If the reports cancel out every vote, the disc has
  no answer (the app falls back to its other sources) until someone files it again.
- Among those, each title (matched by playlist and length) gets the answer with the most weighted votes:
  the movie, an episode number, an extra's category and name, or "skipped".
- Votes are weighted. A title filed exactly as this database's answer was shown on the review page
  (`accepted`) counts as half a vote (`ACCEPTED_WEIGHT`); one that was changed, or identified without
  the database, counts as one. A disc where every title was accepted also counts half towards what
  the disc is. Submissions from 1.0.x (which don't say) count fully, as before.
- An answer counts as confirmed once it has two weighted votes (after reports) and nobody outvotes
  it: two people who checked it, or one who did plus two who accepted it. The app still uses an
  unconfirmed answer, but warns on the review page and doesn't file the disc on its own.
- Confidence is `1 - 0.5^margin` as a percentage, where the margin is the weighted votes for the
  answer less the votes for other answers and the reports against the disc: half a vote ahead is 29,
  one 50, two 75, three 88. A title is never surer than its disc. A locked answer is 100.
- Tracks: the layout (languages, codecs, channels) most of the title's voters saw, and for each audio
  track the commentary name most of them used. The app copies those names when your disc's audio
  tracks line up with them.
- Each install counts once per disc (filing the same disc again replaces your earlier submission).
  Rate limits: 200 submissions a day per install, 400 per IP.

## Privacy

Stored per submission: the disc's fingerprint, label and name as printed on the disc, its format,
what it was identified as, and per title the playlist, length, size, chapter count, the name and
category chosen, whether it was accepted as shown, and its tracks (video codec and size; each audio
track's language, codec, channels and commentary name; each subtitle's language and forced flag).
No subtitle text is sent. Install ids and IP addresses are only kept as salted hashes; IPs only inside daily
rate-limit counters. No file paths, folder names, library details, keys or personal names.

## Local testing

```
npm install wrangler@4
echo SALT=test> .dev.vars & echo ADMIN_TOKEN=test>> .dev.vars
npx wrangler d1 execute shelfrip --local --file=schema.sql
npx wrangler dev --local
```
then set `"community_url": "http://localhost:8787"` in Shelfrip's config.json.

`node tests/test_server.mjs` (from the repository root, Node 22.5 or later) runs the Worker against an
in-memory SQLite database, no Cloudflare needed.
