r"""
community.py - the shared Shelfrip disc database.

When you file a disc (and "share_discs" is on), what you filed is sent to the database:
the disc's fingerprint, and for each title its playlist, length, size and what it turned out
to be (the movie, s01e03, the featurette "Making Of", a clip you skipped). Nothing else: no
file paths, no folder names, no library details, no keys, no names of people. Your install
is identified only by a random id (install_id in config.json), so repeat filings of the
same disc replace each other instead of counting twice.

When anyone rips a disc, identify.py asks the database before TheDiscDB, and uses the answer
most people agreed on. Answers only one person has given yet are used too, but the review
page says so and the disc isn't filed automatically.

The server is in server/ (a Cloudflare Worker); its address is paths.COMMUNITY_URL, or
"community_url" in config.json.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import urllib.parse
import urllib.request
import uuid

import paths

TIMEOUT = 8
PLACEHOLDER = re.compile(r"^(Extra \d+ \(|Unused clip)", re.I)
SOURCE = "the Shelfrip disc database"


def base_url(cfg: dict) -> str:
    return str(cfg.get("community_url") or paths.COMMUNITY_URL or "").rstrip("/")


def install_id(cfg: dict) -> str:
    """This install's random id, made (and saved in config.json) the first time it's needed."""
    iid = str(cfg.get("install_id") or "")
    if re.fullmatch(r"[0-9a-f-]{16,64}", iid):
        return iid
    iid = str(uuid.uuid4())
    try:
        raw = json.loads(paths.CONFIG_PATH.read_text(encoding="utf-8-sig")) if paths.CONFIG_PATH.exists() else {}
        raw["install_id"] = iid
        tmp = paths.CONFIG_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
        tmp.replace(paths.CONFIG_PATH)
    except OSError:
        pass
    cfg["install_id"] = iid
    return iid


def signature(disc: dict) -> str:
    """A fingerprint from the titles MakeMKV lists (length and size of each), for discs without a content hash."""
    parts = sorted(f"{int(t.get('duration_seconds') or 0)}:{int(t.get('size_bytes') or 0)}"
                   for t in disc.get("titles", []) if int(t.get("size_bytes") or 0) > 0)
    if not parts:
        return ""
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:32]


def _http(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if data else "GET",
                                 headers={"User-Agent": paths.USER_AGENT, "Content-Type": "application/json",
                                          "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


# --------------------------------------------------------------------------- look up

def lookup(disc: dict, titles: list[dict], cfg: dict, log=print) -> dict | None:
    """The agreed answer for this disc, in the shape identify.apply_discdb takes, or None."""
    base = base_url(cfg)
    if not base or not cfg.get("use_community", True):
        return None
    h, s = str(disc.get("content_hash") or "").lower(), signature(disc)
    if not h and not s:
        return None
    try:
        ans = _http(f"{base}/v1/disc?" + urllib.parse.urlencode({k: v for k, v in (("h", h), ("s", s)) if v}))
    except Exception as exc:
        log(f"    (Shelfrip disc database lookup failed: {exc})")
        return None
    if not ans.get("found") or not ans.get("kind"):
        return None

    import catalog
    rows = ans.get("titles") or []
    pairs: dict[str, dict] = {}
    used: set[int] = set()
    for t in titles:
        for i, r in enumerate(rows):
            if i in used:
                continue
            same_size = r.get("size_bytes") and r.get("size_bytes") == t.get("size_bytes")
            same_play = (r.get("source_file") and r.get("source_file") == t.get("source_file") and
                         abs((r.get("duration_s") or 0) - t.get("duration_seconds", 0)) <= 2)
            if same_size or same_play:
                row = catalog._as_discdb_row({
                    "role": r.get("role"), "kept": r.get("kept"), "category": r.get("category"),
                    "name": r.get("name") or "", "season": r.get("season"), "episode": r.get("episode"),
                    "size_bytes": r.get("size_bytes"), "duration_s": r.get("duration_s")})
                row["votes"], row["confirmed"] = r.get("votes", 0), bool(r.get("confirmed"))
                row["episode_last"] = str(r["episode_last"]) if r.get("episode_last") else ""
                pairs[t["output_file"]] = row
                used.add(i)
                break
    if len(pairs) < max(1, len(titles) // 2):
        return None
    who = ("checked by hand" if ans.get("locked") else
           f"{ans.get('agree')} of {ans.get('submitters')} people agree" if ans.get("submitters", 0) > 1 else
           "shared by 1 person so far")
    return {
        "kind": ans["kind"], "title": ans.get("title") or "", "year": ans.get("year") or "",
        "tmdb_id": str(ans.get("tmdb_id") or ""), "imdb_id": ans.get("imdb_id") or "", "release": "",
        "disc_name": ans.get("disc_name") or "", "how": "community", "pairs": pairs, "local": False,
        "community": True, "confirmed": bool(ans.get("confirmed") or ans.get("locked")),
        "season": ans.get("season"),
        "source": f"{SOURCE} ({ans.get('title')}; {who})", "src_name": "the Shelfrip disc database",
    }


# --------------------------------------------------------------------------- share

def submission(plan: dict, disc: dict, cfg: dict) -> dict | None:
    """What gets sent for one filed disc (see the top of this file), or None if there's nothing useful."""
    if plan.get("kind") not in ("movie", "tv") or not plan.get("tmdb_id"):
        return None
    import naming
    by_file = {t.get("output_file"): t for t in disc.get("titles", [])}
    out = []
    for it in plan.get("items", []):
        t = by_file.get(it.get("source"), {})
        role = it.get("role")
        row = {"source_file": t.get("source_file") or "", "duration_s": int(it.get("duration_seconds") or
                                                                              t.get("duration_seconds") or 0),
               "size_bytes": t.get("size_bytes"), "chapters": t.get("chapters"), "role": role,
               "kept": it.get("action") == "move"}
        if role == "episode":
            eps = it.get("episodes") or ([it["episode"]] if it.get("episode") else [])
            if not eps:
                continue
            row.update(season=it.get("season") or 0, episode=eps[0], episode_last=eps[-1] if len(eps) > 1 else None)
            sp = it.get("split") if it.get("needs_split") else None
            if sp and sp.get("starts"):
                row["split"] = "chapters " + ",".join(str(x + 1) for x in sp["starts"])
        elif role == "extra":
            name = str(it.get("name") or "")
            row.update(category=it.get("category") or "Other", name="" if PLACEHOLDER.match(name) else name)
        elif role == "edition":
            row["name"] = naming.edition_of(str(it.get("name") or ""))
        out.append(row)
    if not out:
        return None
    return {
        "install_id": install_id(cfg), "app_version": paths.APP_VERSION,
        "disc": {"content_hash": str(disc.get("content_hash") or "").lower(), "signature": signature(disc),
                 "format": plan.get("format") or "", "label": plan.get("disc_label") or "",
                 "name": disc.get("name") or ""},
        "media": {"kind": plan["kind"], "title": plan.get("title") or "", "year": str(plan.get("year") or ""),
                  "tmdb_id": str(plan["tmdb_id"]), "imdb_id": plan.get("imdb_id") or "",
                  "season": plan.get("season") if plan["kind"] == "tv" else None},
        "titles": out,
    }


def share(plan: dict, disc: dict, cfg: dict, log=print) -> None:
    """Send one filed disc in the background. Never holds up or fails filing."""
    base = base_url(cfg)
    if not base or not cfg.get("share_discs", True):
        return
    body = submission(plan, disc, cfg)
    if not body or not (body["disc"]["content_hash"] or body["disc"]["signature"]):
        return

    def run():
        try:
            _http(f"{base}/v1/submit", body)
            log(f"Shared {plan.get('title')} with the Shelfrip disc database.")
            try:  # remembered for the Pioneer badge: nobody had added this disc before you
                import progress
                d = body["disc"]
                progress.note_shared("h:" + d["content_hash"] if d["content_hash"] else "s:" + d["signature"],
                                     first=SOURCE not in str(plan.get("match_source") or ""))
            except Exception:
                pass
        except Exception as exc:
            log(f"(couldn't share {plan.get('title')} with the Shelfrip disc database: {exc})")
    threading.Thread(target=run, daemon=True).start()
