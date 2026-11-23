r"""
plex.py - after filing, ask Plex to scan the new files and check it matched them right.

Needs two settings in config.json (both optional; without them the check is skipped):
    "plex_url":   "http://localhost:32400"   (the PC or NAS running Plex Media Server)
    "plex_token": "..."                       (how to find it:
        https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/)

For each filed file it reports one of:
    ok         Plex has it as the right movie (TMDB id) or the right season/episode
    wrong      Plex has it, but as something else (e.g. a different episode number)
    missing    Plex hasn't picked it up yet (still scanning, or the folder isn't in a library)

Files are found by their file name, so it works even when Plex sees the library under a
different path (e.g. Plex running on a NAS). Only the Python standard library is used.
"""

from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import PureWindowsPath


class Plex:
    def __init__(self, url: str, token: str):
        self.url = url.rstrip("/")
        self.token = token.strip()

    def get(self, endpoint: str, **params) -> dict:
        q = ("?" + urllib.parse.urlencode(params)) if params else ""
        req = urllib.request.Request(self.url + endpoint + q, headers={
            "Accept": "application/json", "X-Plex-Token": self.token,
            "X-Plex-Client-Identifier": "shelfrip", "X-Plex-Product": "Shelfrip"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
        try:
            return json.loads(raw or "{}").get("MediaContainer", {})
        except ValueError:  # some calls (e.g. refresh) answer with an empty or XML body
            return {}

    def sections(self) -> list[dict]:
        return self.get("/library/sections").get("Directory", [])

    def refresh(self, section: str, path: str | None = None) -> None:
        self.get(f"/library/sections/{section}/refresh", **({"path": path} if path else {}))


def from_config(cfg: dict) -> Plex | None:
    url, token = (cfg.get("plex_url") or "").strip(), (cfg.get("plex_token") or "").strip()
    if not url or not token or "paste" in token.lower():
        return None
    return Plex(url, token)


# --------------------------------------------------------------------------- path mapping

def _parts(p: str) -> list[str]:
    return [x for x in re.split(r"[\\/]+", p) if x and not x.endswith(":")]


def map_folder(sections: list[dict], local: str, kind: str) -> tuple[str, str] | None:
    """(section key, folder as Plex sees it) for a folder in your library, or None.

    Matches the end of each library location (e.g. '.../Media Library/TV Shows') against
    the folder names in your path, so 'D:\\Media\\TV Shows\\X' maps to
    '/data/Media Library/TV Shows/X' on a NAS too."""
    want = {"tv": "show", "music": "artist"}.get(kind, "movie")
    lp = [x.lower() for x in _parts(local)]
    best = None
    for s in sections:
        if s.get("type") != want:
            continue
        for loc in s.get("Location", []):
            path = loc.get("path") or ""
            pp = _parts(path)
            for k in range(len(pp), 0, -1):
                tail = [x.lower() for x in pp[-k:]]
                hit = next((i for i in range(len(lp) - k + 1) if lp[i:i + k] == tail), None)
                if hit is not None:
                    if best is None or k > best[0]:
                        sep = "\\" if "\\" in path else "/"
                        rest = _parts(local)[hit + k:]
                        best = (k, str(s["key"]), path.rstrip("\\/") + "".join(sep + r for r in rest))
                    break
    return (best[1], best[2]) if best else None


# --------------------------------------------------------------------------- checking

def _files(item: dict) -> list[str]:
    return [PureWindowsPath(p.get("file", "").replace("/", "\\")).name.lower()
            for m in item.get("Media", []) for p in m.get("Part", [])]


def _guids(item: dict) -> list[str]:
    return [g.get("id", "") for g in item.get("Guid", [])]


def expected(plan: dict) -> list[dict]:
    """One entry per file filed: {file, season, episode} for TV, {file} for movies."""
    out = []
    for it in plan.get("items", []):
        if it.get("action") != "move" or not it.get("filed_to"):
            continue
        files = it["filed_to"] if isinstance(it["filed_to"], list) else [it["filed_to"]]
        eps = it.get("episodes") or ([it["episode"]] if it.get("episode") else [])
        for k, f in enumerate(files):
            e = {"file": PureWindowsPath(f).name, "path": f, "role": it.get("role")}
            if it.get("role") == "episode":
                e["season"] = it.get("season")
                e["episode"] = eps[k] if len(files) > 1 and k < len(eps) else (eps[0] if eps else None)
                e["episode_last"] = eps[-1] if len(files) == 1 and len(eps) > 1 else None
            out.append(e)
    return out


def _find(px: Plex, section: str, plan: dict) -> list[dict]:
    """Plex items (movies, or the show's episodes) that might hold our files."""
    tv = plan.get("kind") == "tv"
    title = plan.get("title") or ""
    items = px.get(f"/library/sections/{section}/all", type=2 if tv else 1, title=title,
                   includeGuids=1).get("Metadata", [])
    tag = f"tmdb://{plan.get('tmdb_id')}"
    if not items or (plan.get("tmdb_id") and not any(tag in _guids(i) for i in items)):
        items = px.get(f"/library/sections/{section}/all", type=2 if tv else 1,
                       includeGuids=1).get("Metadata", [])
        if plan.get("tmdb_id"):
            items = [i for i in items if tag in _guids(i)] or items
    if not tv:
        return items
    eps = []
    for show in items[:30]:
        for e in px.get(f"/library/metadata/{show['ratingKey']}/allLeaves").get("Metadata", []):
            e["_show_guids"] = _guids(show)
            e["_show_title"] = show.get("title")
            eps.append(e)
    return eps


def check(px: Plex, section: str, plan: dict) -> list[dict]:
    want = expected(plan)
    have = _find(px, section, plan)
    by_file = {}
    for item in have:
        for f in _files(item):
            by_file[f] = item
    tag = f"tmdb://{plan.get('tmdb_id')}" if plan.get("tmdb_id") else ""
    out = []
    for w in want:
        item = by_file.get(w["file"].lower())
        r = {"file": w["file"]}
        if not item:
            r.update(state="missing", why="not in Plex yet")
        elif plan.get("kind") == "tv":
            s, e = item.get("parentIndex"), item.get("index")
            show_ok = not tag or tag in item.get("_show_guids", [])
            if not show_ok:
                r.update(state="wrong", why=f"Plex matched the show as \"{item.get('_show_title')}\", not tmdb-{plan.get('tmdb_id')}")
            elif w.get("season") is not None and (s, e) != (w["season"], w["episode"]):
                r.update(state="wrong", why=f"Plex has it as s{s or 0:02d}e{e or 0:02d}")
            else:
                r.update(state="ok", why=f"s{s or 0:02d}e{e or 0:02d} \"{item.get('title') or ''}\"")
        else:
            g = _guids(item)
            if w["role"] == "extra":
                r.update(state="ok", why="extra")
            elif tag and tag not in g:
                r.update(state="wrong", why=f"Plex matched it as \"{item.get('title')}\" ({item.get('year')})")
            else:
                r.update(state="ok", why=f"\"{item.get('title')}\" ({item.get('year')})")
        out.append(r)
    return out


def scan_and_check(cfg: dict, plan: dict, status: dict, wait_s: int = 300, log=print) -> None:
    """Trigger a Plex scan of the filed folder, then check the result. Fills `status` as it goes:
    {state: scanning|done|error|off, summary, files: [...]}."""
    px = from_config(cfg)
    if not px:
        status.update(state="off", summary="Plex check is off (add plex_url and plex_token to config.json)")
        return
    import identify
    try:
        sections = px.sections()
        lib = cfg.get("plex_library_root") or ""
        folder = plan.get("library_dir") or ""
        local = (lib.rstrip("\\/") + "\\" + folder) if lib and not identify.is_full_path(folder) else folder
        mapped = map_folder(sections, local, plan.get("kind") or "movie")
        if not mapped:
            status.update(state="error", summary="Plex has no library that holds " + local)
            return
        section, plex_path = mapped
        status.update(state="scanning", summary="Plex is scanning the new files…")
        px.refresh(section, plex_path)
        deadline, full_scan = time.time() + wait_s, False
        while True:
            time.sleep(10)
            res = check(px, section, plan)
            missing = [r for r in res if r["state"] == "missing"]
            # extras (in sub folders) don't show up as items, so don't wait on them
            missing = [r for r in missing if not any(w["file"] == r["file"] and w["role"] == "extra"
                                                     for w in expected(plan))]
            if not missing or time.time() > deadline:
                break
            if not full_scan and time.time() + 60 > deadline:  # a path scan may miss: scan the whole library once
                px.refresh(section)
                full_scan = True
        res = [r for r in res if not (r["state"] == "missing" and any(
            w["file"] == r["file"] and w["role"] == "extra" for w in expected(plan)))]
        ok = sum(r["state"] == "ok" for r in res)
        wrong = [r for r in res if r["state"] == "wrong"]
        miss = [r for r in res if r["state"] == "missing"]
        parts = [f"Plex: {ok} of {len(res)} matched"]
        if wrong:
            parts.append(f"{len(wrong)} matched wrong")
        if miss:
            parts.append(f"{len(miss)} not showing yet")
        status.update(state="done", summary=", ".join(parts), files=res)
    except Exception as exc:
        status.update(state="error", summary=f"Plex check failed ({exc})")
        log(f"Plex check failed: {exc}")


# --------------------------------------------------------------------------- library report

def audit(cfg: dict) -> dict:
    """Items Plex hasn't matched, or matched to a different TMDB id than the folder name says.

    {"movies": [...], "shows": [...]} with {title, year, folder, problem} each."""
    px = from_config(cfg)
    if not px:
        return {"off": True}
    out = {"movies": [], "shows": []}
    for s in px.sections():
        if s.get("type") not in ("movie", "show"):
            continue
        kind = "movies" if s["type"] == "movie" else "shows"
        items = px.get(f"/library/sections/{s['key']}/all", includeGuids=1).get("Metadata", [])
        for it in items:
            guids = _guids(it)
            files = [p.get("file", "") for m in it.get("Media", []) for p in m.get("Part", [])]
            folder = ""
            if files:
                parts = re.split(r"[\\\\/]", files[0])
                folder = parts[-2] if len(parts) > 1 else ""
            elif it.get("Location"):
                folder = re.split(r"[\\\\/]", it["Location"][0].get("path", ""))[-1]
            want = re.search(r"\{tmdb-(\d+)\}", folder)
            have = [g for g in guids if g.startswith("tmdb://")]
            row = {"title": it.get("title"), "year": it.get("year"), "folder": folder, "section": s.get("title")}
            if not guids or any(g.startswith(("local://", "none://")) for g in guids):
                out[kind].append(dict(row, problem="not matched in Plex"))
            elif want and have and f"tmdb://{want.group(1)}" not in have:
                out[kind].append(dict(row, problem=f"Plex matched it to {have[0].replace('tmdb://', 'tmdb-')}, "
                                                    f"but the folder says tmdb-{want.group(1)}"))
    return out
