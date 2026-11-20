// Shelfrip community disc database: a Cloudflare Worker with a D1 database.
//
// Each time someone files a disc (and has sharing on), the app sends what they filed: the disc's
// fingerprint and, per title, its playlist, length and size and what it turned out to be (the movie,
// episode s01e03, the featurette "Making Of", a skipped clip). When someone else rips the same disc,
// the app asks here first and gets the answer most people agreed on.
//
//   POST /v1/submit           one filed disc               (rate limited per install and per IP)
//   POST /v1/report           "this disc is not <answer>"  (counts against that answer)
//   POST /v1/feedback         a message from the app's Feedback button
//   GET  /v1/disc?h=..&s=..   the agreed answer for a disc (h = content hash, s = title signature)
//   GET  /v1/export           every disc's agreed answer, CC0 (cached for an hour)
//   GET  /v1/stats            counts
//   GET  /v1/admin/recent     latest submissions          (Authorization: Bearer ADMIN_TOKEN)
//   POST /v1/admin/block      {install, why}: hide everything from one install
//   POST /v1/admin/hide       {id, hidden}: hide or show one submission
//   POST /v1/admin/lock       {disc_key, answer|null}: fix a disc's answer by hand
//   GET  /v1/admin/reports    discs people said were wrong, newest first
//   GET  /v1/admin/feedback   feedback, newest first (?all=1 includes ones marked done)
//   POST /v1/admin/feedback   {id, done}: mark feedback done (or not)
//
// Nothing personal is stored: install ids and IPs are only kept as salted hashes (SALT secret),
// IPs only inside daily rate-limit counters.

const MAX_BODY = 128 * 1024;
const MAX_TITLES = 300;
const PER_INSTALL_PER_DAY = 200;
const PER_IP_PER_DAY = 400;
const PER_INSTALL_FEEDBACK = 20;
const PER_IP_FEEDBACK = 40;
const CONFIRM = 2;              // independent installs that must agree before an answer counts as confirmed
const ROLES = new Set(["main", "edition", "episode", "extra", "play_all"]);
const CATEGORIES = new Set(["Featurettes", "Behind the Scenes", "Deleted Scenes", "Interviews", "Scenes",
  "Shorts", "Trailers", "Other"]);

export default {
  async fetch(req, env, ctx) {
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors() });
    const url = new URL(req.url);
    try {
      if (url.pathname === "/" || url.pathname === "/v1") return json({ name: "Shelfrip disc database", version: 1,
        docs: "https://github.com/VandykeConnor/ShelfRip/tree/main/server" });
      if (url.pathname === "/v1/submit" && req.method === "POST") return await submit(req, env);
      if (url.pathname === "/v1/report" && req.method === "POST") return await report(req, env);
      if (url.pathname === "/v1/feedback" && req.method === "POST") return await feedback(req, env);
      if (url.pathname === "/v1/disc" && req.method === "GET") return await lookup(url, env);
      if (url.pathname === "/v1/export" && req.method === "GET") return await exportAll(req, env, ctx);
      if (url.pathname === "/v1/stats" && req.method === "GET") return await stats(env);
      if (url.pathname.startsWith("/v1/admin/")) return await admin(req, url, env);
      return json({ error: "not found" }, 404);
    } catch (e) {
      if (e instanceof Refusal) return json({ error: e.message }, e.status);
      console.error(e && e.stack || e);
      return json({ error: "server error" }, 500);
    }
  },
};

class Refusal extends Error { constructor(msg, status = 400) { super(msg); this.status = status; } }

function cors() {
  return { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization" };
}
function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body), { status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...cors(), ...extra } });
}
async function sha(text) {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, "0")).join("");
}
const today = () => new Date().toISOString().slice(0, 10);
const now = () => Math.floor(Date.now() / 1000);
const str = (v, n = 200) => (v === null || v === undefined) ? "" : String(v).slice(0, n).trim();
const int = v => Number.isFinite(Number(v)) && v !== "" && v !== null ? Math.trunc(Number(v)) : null;

// ------------------------------------------------------------------ submit

function cleanTitle(t) {
  const role = ROLES.has(t.role) ? t.role : null;
  if (!role) return null;
  const out = {
    source_file: str(t.source_file, 80), duration_s: int(t.duration_s), size_bytes: int(t.size_bytes),
    chapters: int(t.chapters), role, kept: t.kept ? 1 : 0,
  };
  if (!out.duration_s && !out.size_bytes) return null;
  if (role === "episode") {
    out.season = int(t.season); out.episode = int(t.episode); out.episode_last = int(t.episode_last);
    if (out.season === null || out.episode === null) return null;
  }
  if (role === "extra") {
    out.category = CATEGORIES.has(t.category) ? t.category : "Other";
    out.name = str(t.name, 150);
  }
  if (role === "edition") out.name = str(t.name, 60);  // just the edition, e.g. "Extended"
  if (t.split) out.split = str(t.split, 200);          // how a multi-episode title was cut
  return out;
}

async function bump(env, key, limit) {
  const day = today();
  const row = await env.DB.prepare(
    "INSERT INTO limits (key, day, n) VALUES (?, ?, 1) ON CONFLICT(key, day) DO UPDATE SET n = n + 1 RETURNING n"
  ).bind(key, day).first();
  if (row && row.n > limit) throw new Refusal("too many submissions today, try again tomorrow", 429);
}

async function body(req) {
  const len = Number(req.headers.get("Content-Length") || 0);
  if (len > MAX_BODY) throw new Refusal("too large", 413);
  const text = await req.text();
  if (text.length > MAX_BODY) throw new Refusal("too large", 413);
  try { return JSON.parse(text); } catch { throw new Refusal("not JSON"); }
}
async function installOf(b, env) {
  const installId = str(b.install_id, 64);
  if (!/^[0-9a-f-]{16,64}$/i.test(installId)) throw new Refusal("bad install_id");
  const install = await sha(env.SALT + "|install|" + installId);
  if (await env.DB.prepare("SELECT 1 FROM blocked WHERE install = ?").bind(install).first())
    throw new Refusal("submissions from this install are blocked", 403);
  return install;
}
function discKeys(d) {
  const hash = str(d.content_hash, 64).toLowerCase(), sig = str(d.signature, 64).toLowerCase();
  if (!hash && !sig) throw new Refusal("disc needs a content_hash or signature");
  if ((hash && !/^[0-9a-f]{16,64}$/.test(hash)) || (sig && !/^[0-9a-f]{16,64}$/.test(sig)))
    throw new Refusal("bad fingerprint");
  return { discKey: hash ? "h:" + hash : "s:" + sig, altKey: hash && sig ? "s:" + sig : null };
}

async function submit(req, env) {
  const b = await body(req);
  const install = await installOf(b, env);
  const d = b.disc || {}, m = b.media || {};
  const { discKey, altKey } = discKeys(d);
  const kind = m.kind === "tv" ? "tv" : m.kind === "movie" ? "movie" : null;
  if (!kind) throw new Refusal("media.kind must be movie or tv");
  const tmdb = str(m.tmdb_id, 20);
  if (tmdb && !/^\d+$/.test(tmdb)) throw new Refusal("bad tmdb_id");
  const titles = (Array.isArray(b.titles) ? b.titles : []).slice(0, MAX_TITLES).map(cleanTitle).filter(Boolean);
  if (!titles.length) throw new Refusal("no titles");

  const ip = req.headers.get("CF-Connecting-IP") || "";
  await bump(env, await sha(env.SALT + "|ip|" + ip), PER_IP_PER_DAY);
  await bump(env, install, PER_INSTALL_PER_DAY);

  // what you file now is your answer: drop any report of yours saying this is what the disc *isn't*
  await env.DB.prepare("DELETE FROM reports WHERE disc_key = ? AND install = ? AND kind = ? AND tmdb_id = ? AND IFNULL(season, -1) = ?")
    .bind(discKey, install, kind, tmdb, kind === "tv" ? (int(m.season) ?? -1) : -1).run();
  await env.DB.prepare(
    `INSERT INTO submissions (disc_key, alt_key, install, created, app_version, format, disc_label, disc_name,
       kind, title, year, tmdb_id, imdb_id, season, titles)
     VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
     ON CONFLICT(disc_key, install) DO UPDATE SET alt_key=excluded.alt_key, created=excluded.created,
       app_version=excluded.app_version, format=excluded.format, disc_label=excluded.disc_label,
       disc_name=excluded.disc_name, kind=excluded.kind, title=excluded.title, year=excluded.year,
       tmdb_id=excluded.tmdb_id, imdb_id=excluded.imdb_id, season=excluded.season, titles=excluded.titles`
  ).bind(discKey, altKey, install, now(), str(b.app_version, 20), str(d.format, 20), str(d.label, 100),
    str(d.name, 200), kind, str(m.title, 200), str(m.year, 4), tmdb, str(m.imdb_id, 20),
    kind === "tv" ? int(m.season) : null, JSON.stringify(titles)).run();
  return json({ ok: true, disc_key: discKey });
}

async function report(req, env) {
  const b = await body(req);
  const install = await installOf(b, env);
  const { discKey, altKey } = discKeys(b.disc || {});
  const w = b.wrong || {}, r = b.instead || {};
  const kind = w.kind === "tv" ? "tv" : w.kind === "movie" ? "movie" : null;
  const tmdb = str(w.tmdb_id, 20);
  if (!kind || !/^\d+$/.test(tmdb)) throw new Refusal("wrong needs kind and tmdb_id");
  const ip = req.headers.get("CF-Connecting-IP") || "";
  await bump(env, await sha(env.SALT + "|ip|" + ip), PER_IP_PER_DAY);
  await bump(env, install, PER_INSTALL_PER_DAY);
  const better = JSON.stringify({ kind: r.kind === "tv" ? "tv" : "movie", title: str(r.title, 200), year: str(r.year, 4),
    tmdb_id: str(r.tmdb_id, 20), season: int(r.season) });
  await env.DB.prepare(
    `INSERT INTO reports (disc_key, alt_key, install, created, kind, tmdb_id, season, better) VALUES (?,?,?,?,?,?,?,?)
     ON CONFLICT(disc_key, install, kind, tmdb_id, season) DO UPDATE SET created=excluded.created, better=excluded.better`
  ).bind(discKey, altKey, install, now(), kind, tmdb, kind === "tv" ? int(w.season) : null, better).run();
  return json({ ok: true });
}

async function feedback(req, env) {
  const b = await body(req);
  const install = await installOf(b, env);
  const title = str(b.title, 200), text = str(b.body, 5000);
  if (!title && !text) throw new Refusal("empty");
  const ip = req.headers.get("CF-Connecting-IP") || "";
  await bump(env, await sha(env.SALT + "|fbip|" + ip), PER_IP_FEEDBACK);
  await bump(env, await sha(env.SALT + "|fb|" + install), PER_INSTALL_FEEDBACK);
  const kind = ["idea", "problem", "other"].includes(b.kind) ? b.kind : "other";
  await env.DB.prepare(
    `INSERT INTO feedback (created, install, kind, title, body, contact, app_version, os) VALUES (?,?,?,?,?,?,?,?)`
  ).bind(now(), install, kind, title, text, str(b.contact, 200), str(b.app_version, 20), str(b.os, 120)).run();
  return json({ ok: true });
}

// ------------------------------------------------------------------ consensus

// What one title "is", as a comparable string. Names are compared ignoring case and spacing.
function answerKey(t) {
  const n = (t.name || "").toLowerCase().replace(/\s+/g, " ").trim();
  if (t.role === "episode") return `episode|${t.season}|${t.episode}|${t.episode_last || ""}|${t.kept}`;
  if (t.role === "extra") return `extra|${t.category}|${n}|${t.kept}`;
  if (t.role === "edition") return `edition|${n}|${t.kept}`;
  return `${t.role}|${t.kept}`;
}
// Which title on the disc this is: the playlist and length (the size wobbles between pressings less
// often than you'd think, but the playlist is what TheDiscDB uses too).
const titleKey = t => t.source_file ? `${t.source_file}|${Math.round((t.duration_s || 0) / 2)}` : `size|${t.size_bytes}`;

const idKey = r => `${r.kind}|${r.tmdb_id}|${r.kind === "tv" ? r.season ?? "" : ""}`;

function consensus(rows, reports = []) {
  if (!rows.length) return null;
  // 1. what the disc is: most installs win, less one for each install that said it's wrong
  const ids = new Map(), against = new Map();
  for (const r of rows) ids.set(idKey(r), [...(ids.get(idKey(r)) || []), r]);
  for (const r of reports) {
    const mine = ids.get(idKey(r)) || [];
    if (!mine.some(x => x.install === r.install)) against.set(idKey(r), (against.get(idKey(r)) || 0) + 1);
  }
  const score = list => list.length - (against.get(idKey(list[0])) || 0);
  const ranked = [...ids.values()].sort((a, b) => score(b) - score(a) || b.length - a.length);
  const agree = ranked[0], first = agree[0];
  const reported = against.get(idKey(first)) || 0;
  if (score(agree) <= 0) return { disputed: true, kind: first.kind, title: first.title, tmdb_id: first.tmdb_id,
    season: first.season, submitters: rows.length, agree: agree.length, reported };
  // 2. what each title is, among those who agree on the disc
  const per = new Map();
  for (const r of agree) {
    for (const t of JSON.parse(r.titles)) {
      const k = titleKey(t);
      if (!per.has(k)) per.set(k, new Map());
      const votes = per.get(k), a = answerKey(t);
      if (!votes.has(a)) votes.set(a, { title: t, n: 0, names: new Map() });
      const v = votes.get(a);
      v.n += 1;
      if (t.name) v.names.set(t.name, (v.names.get(t.name) || 0) + 1);  // the most-used spelling wins
    }
  }
  const titles = [];
  for (const votes of per.values()) {
    const list = [...votes.values()].sort((a, b) => b.n - a.n);
    const best = list[0], second = list[1] ? list[1].n : 0;
    const t = { ...best.title };
    if (best.names.size) t.name = [...best.names.entries()].sort((a, b) => b[1] - a[1])[0][0];
    t.votes = best.n;
    t.total = list.reduce((s, x) => s + x.n, 0);
    t.confirmed = best.n >= CONFIRM && best.n > second;
    titles.push(t);
  }
  titles.sort((a, b) => (b.duration_s || 0) - (a.duration_s || 0));
  return {
    kind: first.kind, title: first.title, year: first.year, tmdb_id: first.tmdb_id, imdb_id: first.imdb_id,
    season: first.season, format: first.format, disc_name: first.disc_name, disc_label: first.disc_label,
    submitters: rows.length, agree: agree.length, reported,
    confirmed: score(agree) >= CONFIRM && score(agree) > (ranked[1] ? score(ranked[1]) : 0),
    titles,
  };
}

async function answerFor(env, key) {
  const lock = await env.DB.prepare("SELECT answer FROM locks WHERE disc_key = ?").bind(key).first();
  if (lock) return { ...JSON.parse(lock.answer), locked: true };
  const { results } = await env.DB.prepare(
    `SELECT * FROM submissions WHERE (disc_key = ?1 OR alt_key = ?1) AND hidden = 0
       AND install NOT IN (SELECT install FROM blocked) ORDER BY created DESC LIMIT 500`).bind(key).all();
  const reps = await env.DB.prepare(
    `SELECT install, kind, tmdb_id, season FROM reports WHERE (disc_key = ?1 OR alt_key = ?1)
       AND install NOT IN (SELECT install FROM blocked)`).bind(key).all();
  return consensus(results, reps.results || []);
}

async function lookup(url, env) {
  const h = str(url.searchParams.get("h"), 64).toLowerCase(), s = str(url.searchParams.get("s"), 64).toLowerCase();
  let found = null, key = "";
  if (h) { key = "h:" + h; found = await answerFor(env, key); }
  if (!found && s) { key = "s:" + s; found = await answerFor(env, key); }
  if (!found) return json({ found: false }, 200, { "Cache-Control": "public, max-age=300" });
  return json({ found: true, disc_key: key, ...found }, 200, { "Cache-Control": "public, max-age=300" });
}

async function exportAll(req, env, ctx) {
  const cache = caches.default, ck = new Request(new URL("/v1/export", req.url).toString());
  const hit = await cache.match(ck);
  if (hit) return hit;
  const { results } = await env.DB.prepare(
    `SELECT DISTINCT disc_key FROM submissions WHERE hidden = 0 UNION SELECT disc_key FROM locks`).all();
  const discs = [];
  for (const r of results) {
    const a = await answerFor(env, r.disc_key);
    if (a && !a.disputed) discs.push({ disc_key: r.disc_key, ...a });
  }
  const res = json({ license: "CC0-1.0", exported_at: new Date().toISOString(), discs }, 200,
    { "Cache-Control": "public, max-age=3600" });
  ctx.waitUntil(cache.put(ck, res.clone()));
  return res;
}

async function stats(env) {
  const s = await env.DB.prepare(
    `SELECT COUNT(DISTINCT disc_key) discs, COUNT(*) submissions, COUNT(DISTINCT install) installs
       FROM submissions WHERE hidden = 0`).first();
  return json(s, 200, { "Cache-Control": "public, max-age=300" });
}

// ------------------------------------------------------------------ admin

async function admin(req, url, env) {
  const auth = req.headers.get("Authorization") || "";
  if (!env.ADMIN_TOKEN || auth !== "Bearer " + env.ADMIN_TOKEN) throw new Refusal("forbidden", 403);
  const p = url.pathname.slice("/v1/admin/".length);
  if (p === "recent" && req.method === "GET") {
    const limit = Math.min(200, int(url.searchParams.get("limit")) || 50);
    const { results } = await env.DB.prepare(
      `SELECT id, disc_key, substr(install, 1, 12) install, created, app_version, format, disc_label, kind, title,
         year, tmdb_id, season, hidden, titles FROM submissions ORDER BY created DESC LIMIT ?`).bind(limit).all();
    return json({ submissions: results.map(r => ({ ...r, titles: JSON.parse(r.titles) })) });
  }
  if (p === "reports" && req.method === "GET") {
    const limit = Math.min(200, int(url.searchParams.get("limit")) || 50);
    const { results } = await env.DB.prepare(
      `SELECT r.disc_key, MAX(r.created) created, r.kind, r.tmdb_id, r.season, COUNT(*) n, MAX(r.better) better,
         (SELECT title FROM submissions s WHERE s.disc_key = r.disc_key AND s.tmdb_id = r.tmdb_id LIMIT 1) title,
         (SELECT disc_label FROM submissions s WHERE s.disc_key = r.disc_key LIMIT 1) disc_label,
         (SELECT 1 FROM locks l WHERE l.disc_key = r.disc_key) locked
       FROM reports r GROUP BY r.disc_key, r.kind, r.tmdb_id, r.season ORDER BY created DESC LIMIT ?`).bind(limit).all();
    const out = [];
    for (const r of results) out.push({ ...r, better: r.better ? JSON.parse(r.better) : null, answer: await answerFor(env, r.disc_key) });
    return json({ reports: out });
  }
  if (p === "feedback" && req.method === "GET") {
    const limit = Math.min(200, int(url.searchParams.get("limit")) || 100);
    const all = url.searchParams.get("all") === "1";
    const { results } = await env.DB.prepare(
      `SELECT id, created, substr(install, 1, 12) install, kind, title, body, contact, app_version, os, done FROM feedback
         ${all ? "" : "WHERE done = 0"} ORDER BY created DESC LIMIT ?`).bind(limit).all();
    return json({ feedback: results });
  }
  const b = req.method === "POST" ? await req.json() : {};
  if (p === "feedback") {
    await env.DB.prepare("UPDATE feedback SET done = ? WHERE id = ?").bind(b.done === false ? 0 : 1, int(b.id)).run();
    return json({ ok: true });
  }
  if (p === "block") {
    const prefix = str(b.install, 64);
    if (prefix.length < 12) throw new Refusal("give at least the first 12 characters of the install");
    const row = await env.DB.prepare("SELECT install FROM submissions WHERE install LIKE ? LIMIT 1").bind(prefix + "%").first();
    if (!row) throw new Refusal("no such install", 404);
    await env.DB.prepare("INSERT OR REPLACE INTO blocked VALUES (?, ?, ?)").bind(row.install, str(b.why), now()).run();
    return json({ ok: true });
  }
  if (p === "hide") {
    await env.DB.prepare("UPDATE submissions SET hidden = ? WHERE id = ?").bind(b.hidden === false ? 0 : 1, int(b.id)).run();
    return json({ ok: true });
  }
  if (p === "lock") {
    const key = str(b.disc_key, 80);
    if (!key) throw new Refusal("disc_key needed");
    if (b.answer === null) await env.DB.prepare("DELETE FROM locks WHERE disc_key = ?").bind(key).run();
    else await env.DB.prepare("INSERT OR REPLACE INTO locks VALUES (?, ?, ?)").bind(key, JSON.stringify(b.answer), now()).run();
    return json({ ok: true });
  }
  throw new Refusal("not found", 404);
}

