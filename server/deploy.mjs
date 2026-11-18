// deploy.mjs - puts the Shelfrip disc database on your Cloudflare account (free tier).
//
// Run "Deploy Database.bat" (or: node deploy.mjs) from this folder. It:
//   1. signs you in to Cloudflare (a browser window opens the first time),
//   2. creates the D1 database "shelfrip" (once) and its tables,
//   3. deploys the Worker, and
//   4. gives it two secrets: SALT (hashes install ids and IPs) and ADMIN_TOKEN (for /v1/admin).
// Both secrets are kept in .secrets.json next to this file, which is never committed. Keep it:
// a new SALT would make every install look new. Running this again just redeploys.

import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
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

  step("Deploying the Worker");
  const out = wranglerOut(["deploy"]);
  process.stdout.write(out);
  const url = (out.match(/https:\/\/[a-z0-9.-]+\.workers\.dev/i) || [""])[0];

  step("Setting its secrets");
  const sf = path.join(HERE, ".secrets.json");
  const secrets = fs.existsSync(sf) ? JSON.parse(fs.readFileSync(sf, "utf8")) : {
    SALT: crypto.randomBytes(32).toString("hex"), ADMIN_TOKEN: crypto.randomBytes(24).toString("hex"),
  };
  fs.writeFileSync(sf, JSON.stringify({ ...secrets, url }, null, 2));
  for (const k of ["SALT", "ADMIN_TOKEN"]) wrangler(["secret", "put", k], { input: secrets[k] + "\n", quiet: true });

  step("Done");
  console.log(`The Shelfrip disc database is at:\n\n    ${url || "(see the deploy output above)"}\n`);
  console.log(`Check it: ${url}/v1/stats`);
  console.log(`Your admin token is in ${sf} (keep it private).`);
  console.log("Send the address to Claude so the app can be pointed at it.");
} catch (e) {
  console.error(`\n${e.message}. Copy the messages above to Claude.`);
  process.exit(1);
}
