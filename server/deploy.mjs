// deploy.mjs - puts the Shelfrip disc database on your Cloudflare account (free tier).
//
// Run "Deploy Database.bat" (or: node deploy.mjs) from this folder. It:
//   1. signs you in to Cloudflare (a browser window opens the first time),
//   2. creates the D1 database "shelfrip" (once) and its tables, and applies migrations/ (once each),
//   3. deploys the Worker, and
//   4. gives it its secrets: SALT (hashes install ids and IPs), ADMIN_TOKEN (for /v1/admin) and
//      TMDB_KEY (the shared TMDB key behind /v1/tmdb; asked for once, Enter skips it).
// The secrets are kept in .secrets.json next to this file, which is never committed. Keep it:
// a new SALT would make every install look new. Running this again just redeploys.

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline/promises";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
process.chdir(HERE);
const DB = "shelfrip";

function wrangler(args, { input, quiet } = {}) {
  const r = spawnSync("npx", ["--yes", "wrangler@4", ...args], {
    encoding: "utf8", shell: process.platform === "win32", input,
    stdio: [input === undefined ? "inherit" : "pipe", quiet ? "pipe" : "inherit", quiet ? "pipe" : "inherit"],
  });
  if (r.status !== 0) {
    if (quiet) process.stderr.write((r.stdout || "") + (r.stderr || ""));
    throw new Error(`wrangler ${args.join(" ")} failed`);
  }
  return r.stdout || "";
}
function wranglerOut(args, input) {  // like wrangler(), but returns what it printed
  const r = spawnSync("npx", ["--yes", "wrangler@4", ...args], {
    encoding: "utf8", shell: process.platform === "win32", input,
    stdio: [input === undefined ? "inherit" : "pipe", "pipe", "pipe"],
  });
  const out = (r.stdout || "") + (r.stderr || "");
  if (r.status !== 0) { process.stderr.write(out); throw new Error(`wrangler ${args.join(" ")} failed`); }
  return out;
}

function step(t) { console.log(`\n== ${t}`); }

try {
  step("Signing in to Cloudflare");
  const who = spawnSync("npx", ["--yes", "wrangler@4", "whoami"], { encoding: "utf8", shell: process.platform === "win32" });
  if (!/associated with the email|You are logged in/i.test((who.stdout || "") + (who.stderr || ""))) wrangler(["login"]);

  step(`Finding or creating the database "${DB}"`);
  let list = JSON.parse(wranglerOut(["d1", "list", "--json"]).replace(/^[^\[]*/s, ""));
  let db = list.find(d => d.name === DB);
  if (!db) {
    wrangler(["d1", "create", DB]);
    list = JSON.parse(wranglerOut(["d1", "list", "--json"]).replace(/^[^\[]*/s, ""));
    db = list.find(d => d.name === DB);
  }
  if (!db) throw new Error("couldn't create the database");
  const id = db.uuid || db.database_id;
  const toml = fs.readFileSync("wrangler.toml", "utf8").replace(/database_id = ".*"/, `database_id = "${id}"`);
  fs.writeFileSync("wrangler.toml", toml);
  console.log(`database ${DB}: ${id}`);

  step("Creating the tables (safe to repeat)");
  wrangler(["d1", "execute", DB, "--remote", "--file=schema.sql", "--yes"]);

  step("Updating the tables (safe to repeat)");
  for (const f of fs.readdirSync("migrations").filter(f => f.endsWith(".sql")).sort()) {
    const r = spawnSync("npx", ["--yes", "wrangler@4", "d1", "execute", DB, "--remote", `--file=migrations/${f}`, "--yes"],
      { encoding: "utf8", shell: process.platform === "win32", stdio: ["inherit", "pipe", "pipe"] });
    const out = (r.stdout || "") + (r.stderr || "");
    if (r.status === 0) console.log(`${f}: applied`);
    else if (/duplicate column|already exists/i.test(out)) console.log(`${f}: already in`);
    else { process.stderr.write(out); throw new Error(`migration ${f} failed`); }
  }

  step("Deploying the Worker");
  const tryDeploy = () => spawnSync("npx", ["--yes", "wrangler@4", "deploy"], {
    encoding: "utf8", shell: process.platform === "win32", stdio: ["inherit", "pipe", "pipe"] });
  let r = tryDeploy();
  let out = (r.stdout || "") + (r.stderr || "");
  if (r.status !== 0 && /workers\.dev subdomain/i.test(out)) {
    // A new Cloudflare account has to pick its workers.dev name once: let wrangler ask for it.
    console.log("Cloudflare needs a workers.dev name for your account (once). Answer y, then type a name.");
    spawnSync("npx", ["--yes", "wrangler@4", "deploy"], { shell: process.platform === "win32", stdio: "inherit" });
    r = tryDeploy();
    out = (r.stdout || "") + (r.stderr || "");
  }
  process.stdout.write(out);
  if (r.status !== 0) throw new Error("wrangler deploy failed");
  const url = (out.match(/https:\/\/[a-z0-9.-]+\.workers\.dev/i) || [""])[0];

  step("Setting its secrets");
  const sf = path.join(HERE, ".secrets.json");
  const secrets = fs.existsSync(sf) ? JSON.parse(fs.readFileSync(sf, "utf8")) : {
    SALT: crypto.randomBytes(32).toString("hex"), ADMIN_TOKEN: crypto.randomBytes(24).toString("hex"),
  };
  if (secrets.TMDB_KEY === undefined) {
    console.log("The shared TMDB key lets people use Shelfrip without a TMDB key of their own.\n" +
      "Paste the API key (or API Read Access Token) of the TMDB app you registered for Shelfrip,\n" +
      "or just press Enter to leave it off (you can add it later by deleting TMDB_KEY from .secrets.json).");
    const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
    secrets.TMDB_KEY = (await rl.question("TMDB key: ")).trim();
    rl.close();
  }
  fs.writeFileSync(sf, JSON.stringify({ ...secrets, url }, null, 2));
  for (const k of ["SALT", "ADMIN_TOKEN", "TMDB_KEY"])
    if (secrets[k]) wrangler(["secret", "put", k], { input: secrets[k] + "\n", quiet: true });

  step("Done");
  console.log(`The Shelfrip disc database is at:\n\n    ${url || "(see the deploy output above)"}\n`);
  console.log(`Check it: ${url}/v1/stats`);
  console.log(`Your admin token is in ${sf} (keep it private).`);
  console.log("Send the address to Claude so the app can be pointed at it.");
} catch (e) {
  console.error(`\n${e.message}. Copy the messages above to Claude.`);
  process.exit(1);
}
