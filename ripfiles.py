"""
ripfiles.py - which ripped file belongs to which title.

MakeMKV names each title's file from a template in its own Preferences (Expert mode >
Advanced > "Default output file name template"). The default ends in {_t:N2}, so the titles
of a disc get "Name_t00.mkv", "Name_t01.mkv"... and the scan (`makemkvcon info`) tells
Shelfrip each name up front. A template without the title number gives every title the same
name in the scan, while the files written to disk still come out different. Shelfrip then
looked for one name for every title: it saw the same file for all of them, thought the rest
had failed and ripped them all again, and the Review page showed (and filed, and played) that
one file for every title.

So:
  unclash(disc)              before ripping: give titles that share a name their own name,
                             "<name>_tNN.mkv", which is what MakeMKV writes for them
  match_files(folder, disc)  after ripping (and for rips made before this fix): point each
                             title at the file that really holds it, by MakeMKV's _tNN
                             suffix, then by length (MKVToolNix), then by size
"""

from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path


def clashing(disc: dict) -> set[str]:
    """File names the scan gave to more than one title."""
    n = Counter(t.get("output_file") for t in disc.get("titles", []) if t.get("output_file"))
    return {name for name, k in n.items() if k > 1}


def own_name(name: str, tid: int) -> str:
    """'Mortal Kombat II.mkv', title 3 -> 'Mortal Kombat II_t03.mkv' (MakeMKV's own suffix)."""
    p = Path(name)
    stem = re.sub(r"_t\d+$", "", p.stem)
    return f"{stem}_t{int(tid):02d}{p.suffix or '.mkv'}"


def unclash(disc: dict) -> int:
    """Give each title that shares its file name with another title a name of its own. The name
    MakeMKV gave is kept as makemkv_name. Returns how many titles were renamed."""
    clash = clashing(disc)
    n = 0
    for t in disc.get("titles", []):
        name = t.get("output_file")
        if name in clash:
            t["makemkv_name"] = name
            t["output_file"] = own_name(name, t["title_id"])
            n += 1
    if n:
        disc["name_clash"] = True
    return n


def _length(cfg: dict, path: Path) -> float:
    """The file's length in seconds (MKVToolNix), or 0 when it can't be read."""
    try:
        import split
        mkvmerge = split.tool(cfg, "mkvmerge")
        if not mkvmerge:
            return 0
        r = subprocess.run([mkvmerge, "-J", str(path)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return ((json.loads(r.stdout or "{}").get("container", {}).get("properties", {}).get("duration") or 0)
                / 1e9)
    except Exception:
        return 0


def _close(a: float, b: float, rel: float, least: float = 0) -> bool:
    return abs(a - b) <= max(least, rel * max(a, b))


def match_files(folder: Path, disc: dict, cfg: dict | None = None, length=None) -> bool:
    """Point each title at the MKV in folder that really holds it. Titles that share a file name,
    or whose file isn't there, are matched with the files no other title claims. A title with no
    file left gets its own name (not on disk, so it counts as not ripped). Returns True if any
    title's file changed. length(path) -> seconds can be passed in (tests)."""
    cfg = cfg or {}
    length = length or (lambda p: _length(cfg, p))
    titles = [t for t in disc.get("titles", []) if t.get("output_file")]
    if not titles:
        return False
    try:
        files = {p.name: p for p in folder.glob("*.mkv")}
    except OSError:
        return False
    clash = clashing(disc)
    settled = [t for t in titles if t["output_file"] not in clash and t["output_file"] in files]
    need = [t for t in titles if t not in settled]
    if not need:
        return False
    free = [files[n] for n in sorted(files) if n not in {t["output_file"] for t in settled}]
    got: dict[int, str] = {}

    # 1. MakeMKV's own "_tNN" suffix names the title
    by_tid = {t["title_id"]: t for t in need}
    for p in list(free):
        m = re.search(r"_t(\d+)$", p.stem)
        t = by_tid.get(int(m.group(1))) if m else None
        if t and t["title_id"] not in got and _fits(t, p, length):
            got[t["title_id"]] = p.name
            free.remove(p)

    # 2. the rest by length, then by size: the closest pair first
    left = [t for t in need if t["title_id"] not in got]
    if left and free:
        lens = {p.name: length(p) for p in free}
        pairs = []
        for t in left:
            want_s, want_b = t.get("duration_seconds") or 0, t.get("size_bytes") or 0
            for p in free:
                got_s, size = lens.get(p.name) or 0, p.stat().st_size
                if got_s and want_s:
                    if not _close(got_s, want_s, 0.02, 10):
                        continue
                    score = (0, abs(got_s - want_s), abs(size - want_b))
                elif want_b:
                    if not _close(size, want_b, 0.1):
                        continue
                    score = (1, 0, abs(size - want_b))
                else:
                    continue
                pairs.append((score, t["title_id"], p.name))
        used: set[str] = set()
        for _, tid, name in sorted(pairs):
            if tid not in got and name not in used:
                got[tid], _ = name, used.add(name)

    changed = False
    for t in need:
        new = got.get(t["title_id"])
        if new is None:  # nothing on disk for it (a title that failed or was left out)
            new = t["output_file"] if t["output_file"] not in clash else own_name(t["output_file"], t["title_id"])
        if new != t["output_file"]:
            t.setdefault("makemkv_name", t["output_file"])
            t["output_file"] = new
            changed = True
    if changed:
        disc["name_clash"] = True
    return changed


def _fits(t: dict, p: Path, length) -> bool:
    """Does the file named with this title's number look like it? (a suffix match is trusted unless
    the length is plainly wrong, as when the user's template uses _t for something else)."""
    want = t.get("duration_seconds") or 0
    got = length(p) if want else 0
    return not (got and want) or _close(got, want, 0.02, 10)


def repair(folder: Path, cfg: dict | None = None) -> bool:
    """Fix disc_info.json of a finished rip whose titles point at the wrong files (rips made before
    this fix). Returns True if it was changed."""
    info = folder / "disc_info.json"
    try:
        disc = json.loads(info.read_text(encoding="utf-8"))
    except Exception:
        return False
    if disc.get("kind") == "music" or not match_files(folder, disc, cfg):
        return False
    names = {p.name for p in folder.glob("*.mkv")}
    for t in disc.get("titles", []):
        if "ripped" in t:
            t["ripped"] = t.get("output_file") in names
    tmp = info.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(disc, indent=2), encoding="utf-8")
    tmp.replace(info)
    return True
