// test_server.mjs - the disc database (server/worker.js) against an in-memory SQLite stand-in for D1.
// Run: node tests/test_server.mjs   (needs Node 22.5 or later; tests/run_all.py runs it when Node is there)

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

let DatabaseSync;
try { ({ DatabaseSync } = await import("node:sqlite")); }
catch { console.log("skipped: this Node has no node:sqlite (needs 22.5 or later)"); process.exit(0); }

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const worker = (await import(pathToFileURL(path.join(ROOT, "server", "worker.js")).href)).default;

// just enough of D1: prepare().bind().first()/all()/run()
function d1(db) {
  const wrap = (sql, args = []) => ({
    bind: (...a) => wrap(sql, a),
    first: async () => db.prepare(sql).get(...args) ?? null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
    run: async () => db.prepare(sql).run(...args),
  });
  return { prepare: sql => wrap(sql) };
}

function freshEnv({ oldSchema = false } = {}) {
  const db = new DatabaseSync(":memory:");
  let schema = fs.readFileSync(path.join(ROOT, "server", "schema.sql"), "utf8");
  if (oldSchema) schema = schema.replace(/\n\s*accepted\s+INTEGER[^\n]*/, "").replace(/\n\s*proposed\s+TEXT[^\n]*/, "");
  db.exec(schema);
  for (const f of fs.readdirSync(path.join(ROOT, "server", "migrations")).sort()) {
    try { db.exec(fs.readFileSync(path.join(ROOT, "server", "migrations", f), "utf8")); }
    catch (e) { assert.match(String(e.message), /duplicate column/); }  // fresh tables already have it
  }
  return { DB: d1(db), SALT: "test", ADMIN_TOKEN: "admin" };
}

let ip = 0;
async function call(env, method, p, body) {
  const req = new Request("http://db.test" + p, {
    method, body: body ? JSON.stringify(body) : undefined,
    headers: { "Content-Type": "application/json", "CF-Connecting-IP": `10.0.0.${++ip}` } });
  const res = await worker.fetch(req, env, { waitUntil() {} });
  return { status: res.status, body: await res.json() };
}

const HASH = "ab".repeat(16);
const install = n => `0000000${n}-aaaa-bbbb-cccc-dddddddddddd`;
const tracks = (comName = "") => ({
  video: { codec: "MPEG2", res: "720x480" },
  audio: [{ lang: "eng", codec: "AC3", ch: 6 }, { lang: "eng", codec: "AC3", ch: 2, commentary: 1, ...(comName ? { name: comName } : {}) }],
  subs: [{ lang: "eng" }, { lang: "fra", forced: 1 }],
});
function filing(n, { accepted = false, extraName = "Making Of", comName = "", tmdb = "603" } = {}) {
  const acc = accepted ? { accepted: true } : {};
  return {
    install_id: install(n), app_version: "1.1.0",
    disc: { content_hash: HASH, signature: "", format: "DVD", label: "MATRIX", name: "The Matrix" },
    media: { kind: "movie", title: "The Matrix", year: "1999", tmdb_id: tmdb, imdb_id: "tt0133093" },
    titles: [
      { source_file: "00001.mpls", duration_s: 8160, size_bytes: 7e9, chapters: 32, role: "main", kept: true,
        tracks: tracks(comName), ...acc },
      { source_file: "00002.mpls", duration_s: 1200, size_bytes: 5e8, chapters: 4, role: "extra", kept: true,
        category: "Featurettes", name: extraName, ...acc },
    ],
  };
}
const look = env => call(env, "GET", `/v1/disc?h=${HASH}`);
const main = ans => ans.titles.find(t => t.role === "main");

const tests = {
  async "one person who checked it: 50% sure, not confirmed"() {
    const env = freshEnv();
    assert.equal((await call(env, "POST", "/v1/submit", filing(1))).status, 200);
    const { body } = await look(env);
    assert.equal(body.found, true);
    assert.equal(body.confirmed, false);
    assert.equal(body.confidence, 50);
    assert.equal(main(body).confidence, 50);
    assert.equal(main(body).votes, 1);
  },

  async "clicking through counts half: one check plus one accept isn't confirmed"() {
    const env = freshEnv();
    await call(env, "POST", "/v1/submit", filing(1));
    await call(env, "POST", "/v1/submit", filing(2, { accepted: true }));
    const { body } = await look(env);
    assert.equal(body.agree, 2);
    assert.equal(body.weight, 1.5);
    assert.equal(body.confirmed, false);
    assert.equal(main(body).confirmed, false);
    assert.equal(main(body).weight, 1.5);
    assert.equal(main(body).confidence, 65);
    assert.equal(main(body).accepted, undefined);
  },

  async "two people who checked it confirm it (75%)"() {
    const env = freshEnv();
    await call(env, "POST", "/v1/submit", filing(1));
    await call(env, "POST", "/v1/submit", filing(2));
    const { body } = await look(env);
    assert.equal(body.confirmed, true);
    assert.equal(main(body).confirmed, true);
    assert.equal(main(body).confidence, 75);
  },

  async "a changed title counts fully even when the rest was accepted"() {
    const env = freshEnv();
    await call(env, "POST", "/v1/submit", filing(1, { extraName: "" }));
    const f = filing(2, { accepted: true, extraName: "Making Of" });
    delete f.titles[1].accepted;  // renamed the extra: that title was checked
    await call(env, "POST", "/v1/submit", f);
    await call(env, "POST", "/v1/submit", filing(3, { extraName: "Making Of" }));
    const { body } = await look(env);
    const extra = body.titles.find(t => t.role === "extra");
    assert.equal(extra.name, "Making Of");
    assert.equal(extra.weight, 2);
    assert.equal(extra.confidence, 50);  // 2 for, 1 against
    assert.equal(body.weight, 3);        // not every title was accepted, so the disc vote is full
  },

  async "reports lower confidence"() {
    const env = freshEnv();
    await call(env, "POST", "/v1/submit", filing(1));
    await call(env, "POST", "/v1/submit", filing(2));
    await call(env, "POST", "/v1/report", { install_id: install(3), disc: { content_hash: HASH },
      wrong: { kind: "movie", tmdb_id: "603" }, instead: { kind: "movie", tmdb_id: "604" } });
    const { body } = await look(env);
    assert.equal(body.reported, 1);
    assert.equal(body.confirmed, false);
    assert.equal(body.confidence, 50);
    assert.equal(main(body).confidence, 50);
  },

  async "tracks are kept, cleaned, and commentary names agreed on"() {
    const env = freshEnv();
    await call(env, "POST", "/v1/submit", filing(1, { comName: "Commentary with the Cast" }));
    await call(env, "POST", "/v1/submit", filing(2, { comName: "Commentary with the Cast" }));
    const junk = filing(3);
    junk.titles[0].tracks.audio[0].lang = "english!!";
    await call(env, "POST", "/v1/submit", junk);
    const { body } = await look(env);
    const tr = main(body).tracks;
    assert.deepEqual(tr.video, { codec: "MPEG2", res: "720x480" });
    assert.equal(tr.audio.length, 2);
    assert.equal(tr.audio[1].commentary, 1);
    assert.equal(tr.audio[1].name, "Commentary with the Cast");
    assert.deepEqual(tr.subs, [{ lang: "eng" }, { lang: "fra", forced: 1 }]);
    const recent = await worker.fetch(new Request("http://db.test/v1/admin/recent", {
      headers: { Authorization: "Bearer admin" } }), env, {});
    const rows = (await recent.json()).submissions;
    const odd = rows.find(r => r.titles[0].tracks.audio[0].lang === "");
    assert.ok(odd, "a bad language code is dropped");
  },

  async "1.0.1 filings (no tracks, no accepted) still count fully"() {
    const env = freshEnv();
    for (const n of [1, 2]) {
      const f = filing(n);
      f.app_version = "1.0.1";
      for (const t of f.titles) delete t.tracks;
      await call(env, "POST", "/v1/submit", f);
    }
    const { body } = await look(env);
    assert.equal(body.confirmed, true);
    assert.equal(main(body).votes, 2);
    assert.equal(main(body).tracks, undefined);
  },

  async "a migrated old database works"() {
    const env = freshEnv({ oldSchema: true });
    await call(env, "POST", "/v1/submit", filing(1, { accepted: true }));
    const { body } = await look(env);
    assert.equal(body.weight, 0.5);
    assert.equal(body.confidence, 29);
  },

  async "what Shelfrip suggested is kept, and changed titles are marked"() {
    const env = freshEnv();
    const kept = filing(1);
    kept.proposed = { known: true };
    kept.titles[1].changed = true;               // renamed the extra
    const picked = filing(2);
    picked.disc.content_hash = "cd".repeat(16);
    picked.proposed = { known: true, kind: "movie", title: "The Matrix Reloaded", year: "2003", tmdb_id: "604", season: null };
    const old = filing(3);
    old.disc.content_hash = "ef".repeat(16);
    for (const f of [kept, picked, old]) assert.equal((await call(env, "POST", "/v1/submit", f)).status, 200);
    const recent = await worker.fetch(new Request("http://db.test/v1/admin/recent", {
      headers: { Authorization: "Bearer admin" } }), env, {});
    const rows = (await recent.json()).submissions;
    const by = h => rows.find(r => r.disc_key === "h:" + h);
    assert.deepEqual(by(HASH).proposed, {});
    assert.equal(by(HASH).titles[1].changed, 1);
    assert.equal(by(HASH).titles[0].changed, undefined);
    assert.deepEqual(by("cd".repeat(16)).proposed, { kind: "movie", title: "The Matrix Reloaded", year: "2003", tmdb_id: "604", season: null });
    assert.equal(by("ef".repeat(16)).proposed, null);  // an older app: not known
  },

  async "a locked answer is 100% sure"() {
    const env = freshEnv();
    await worker.fetch(new Request("http://db.test/v1/admin/lock", { method: "POST",
      headers: { Authorization: "Bearer admin", "Content-Type": "application/json" },
      body: JSON.stringify({ disc_key: "h:" + HASH, answer: { kind: "movie", title: "The Matrix", tmdb_id: "603", titles: [] } }) }),
      env, {});
    const { body } = await look(env);
    assert.equal(body.locked, true);
    assert.equal(body.confidence, 100);
  },

  async "shared TMDB key: passes allowed calls on with the server's key"() {
    const env = { ...freshEnv(), TMDB_KEY: "secretkey" };
    const seen = [], realFetch = globalThis.fetch;
    globalThis.fetch = async (u, o) => { seen.push({ u: String(u), o });
      return new Response(JSON.stringify({ results: [{ id: 603 }] }), { status: 200 }); };
    try {
      const r = await call(env, "GET", "/v1/tmdb/search/movie?query=The%20Matrix&include_adult=false");
      assert.equal(r.status, 200);
      assert.equal(r.body.results[0].id, 603);
      assert.equal(seen.length, 1);
      const u = new URL(seen[0].u);
      assert.equal(u.origin + u.pathname, "https://api.themoviedb.org/3/search/movie");
      assert.equal(u.searchParams.get("api_key"), "secretkey");
      assert.equal(u.searchParams.get("query"), "The Matrix");
      for (const p of ["/v1/tmdb/movie/603", "/v1/tmdb/tv/1399/season/2", "/v1/tmdb/tv/1399/external_ids",
                       "/v1/tmdb/movie/603/credits", "/v1/tmdb/tv/1399/aggregate_credits", "/v1/tmdb/configuration"])
        assert.equal((await call(env, "GET", p)).status, 200, p);
      // anything else is refused before TMDB is asked
      const before = seen.length;
      assert.equal((await call(env, "GET", "/v1/tmdb/account")).status, 404);
      assert.equal((await call(env, "GET", "/v1/tmdb/movie/603/account_states")).status, 404);
      assert.equal((await call(env, "GET", "/v1/tmdb/search/movie?query=x&api_key=mine")).status, 400);
      assert.equal(seen.length, before);
      // a v4 token goes in the header, never the address
      env.TMDB_KEY = "eyJabc";
      await call(env, "GET", "/v1/tmdb/movie/603");
      assert.equal(seen.at(-1).o.headers.Authorization, "Bearer eyJabc");
      assert.equal(new URL(seen.at(-1).u).searchParams.get("api_key"), null);
    } finally { globalThis.fetch = realFetch; }
  },

  async "shared TMDB key: missing key, TMDB errors and the daily limit"() {
    const env = freshEnv();
    assert.equal((await call(env, "GET", "/v1/tmdb/movie/603")).status, 503);
    env.TMDB_KEY = "k";
    const realFetch = globalThis.fetch;
    let status = 429;
    globalThis.fetch = async () => new Response("{}", { status, headers: { "Retry-After": "3" } });
    try {
      assert.equal((await call(env, "GET", "/v1/tmdb/movie/603")).status, 429);
      status = 404;
      assert.equal((await call(env, "GET", "/v1/tmdb/movie/999999")).status, 404);
      status = 500;
      assert.equal((await call(env, "GET", "/v1/tmdb/movie/603")).status, 502);
      status = 200;
      const req = () => worker.fetch(new Request("http://db.test/v1/tmdb/movie/603",
        { headers: { "CF-Connecting-IP": "10.9.9.9" } }), env, { waitUntil() {} });
      for (let i = 0; i < 3000; i++) assert.equal((await req()).status, 200);
      const over = await req();
      assert.equal(over.status, 429);
      assert.match((await over.json()).error, /own free key/);
    } finally { globalThis.fetch = realFetch; }
  },
  async "feedback keeps logs for problems and other, never for ideas"() {
    const env = freshEnv();
    for (const kind of ["problem", "other", "idea"])
      assert.equal((await call(env, "POST", "/v1/feedback", { install_id: install(1), kind, title: kind, logs: "line 1\nline 2" })).status, 200);
    assert.equal((await call(env, "POST", "/v1/feedback", { install_id: install(1), kind: "problem", title: "big", logs: "x".repeat(70000) })).status, 200);
    const res = await worker.fetch(new Request("http://db.test/v1/admin/feedback",
      { headers: { Authorization: "Bearer admin" } }), env, { waitUntil() {} });
    const fb = Object.fromEntries((await res.json()).feedback.map(f => [f.title, f.logs]));
    assert.equal(fb.problem, "line 1\nline 2");
    assert.equal(fb.other, "line 1\nline 2");
    assert.equal(fb.idea, null);
    assert.equal(fb.big.length, 60000);
  },
};

let failed = 0;
for (const [name, fn] of Object.entries(tests)) {
  try { await fn(); console.log("ok   " + name); }
  catch (e) { failed++; console.log("FAIL " + name + "\n     " + (e.stack || e).split("\n").slice(0, 3).join("\n     ")); }
}
console.log(failed ? `${failed} failed` : "All server tests passed.");
process.exit(failed ? 1 : 0);
