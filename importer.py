"""
importer.py - bring MKVs you ripped before (with MakeMKV on its own, or anything else) into
Shelfrip to be named and filed like a fresh rip.

The videos go into a new folder in the rip folder, with a disc_info.json built from what
MKVToolNix reads in each file (length, chapters, tracks), so the naming step treats the folder
like a disc Shelfrip ripped itself: the folder's name is used as the disc label, the files are
matched against TMDB, the shared disc database and your library, and the result waits on the
Review tab. On the same drive the files are moved (instant); on another drive they're copied and
the originals are left where they were.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import threading
from pathlib import Path

VIDEO = {".mkv"}
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
JOBS: dict[str, dict] = {}  # {source folder: {state, done, total, folder, error}} for the page to poll
LOCK = threading.Lock()


def videos(src: Path) -> list[Path]:
    """The MKVs directly in this folder, in name order (MakeMKV's title_t00, title_t01, ...)."""
    try:
        return sorted((p for p in src.iterdir() if p.is_file() and p.suffix.lower() in VIDEO),
                      key=lambda p: p.name.lower())
    except OSError:
        return []


def _inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def problem(src: Path, rip_root: Path, library_roots: list[Path]) -> str:
    """Why this folder can't be imported, else ''."""
    if not str(src).strip() or not src.is_dir():
        return "That folder doesn't exist."
    if _inside(src, rip_root):
        return "That folder is already in the rip folder. Pick a folder of videos from somewhere else."
    if _inside(rip_root, src):
        return "Pick a folder of videos, not one that holds the rip folder."
    for lib in library_roots:
        if lib and str(lib).strip() and lib.is_dir() and (_inside(src, lib) or _inside(lib, src)):
            return "That folder is part of your media library. Pick a folder of videos that aren't filed yet."
    if not videos(src):
        return "There are no MKV files directly in that folder."
    return ""


def _title_id(p: Path, i: int, used: set[int]) -> int:
    m = re.search(r"_t(\d{2,3})\.mkv$", p.name, re.I)  # MakeMKV: "title_t03.mkv", "Movie_t03.mkv"
    tid = int(m.group(1)) if m else i
    while tid in used:
        tid += 1000
    used.add(tid)
    return tid


def _hms(seconds: float) -> str:
    s = int(round(seconds))
    return f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}"


CODECS = {"V_MPEG2": "Mpeg2", "V_MPEG4/ISO/AVC": "H264", "V_MPEGH/ISO/HEVC": "HEVC", "V_MS/VFW/FOURCC": "VC-1",
          "A_AC3": "AC3", "A_EAC3": "E-AC3", "A_DTS": "DTS", "A_TRUEHD": "TrueHD", "A_PCM/INT/LIT": "LPCM",
          "A_FLAC": "FLAC", "A_AAC": "AAC", "S_HDMV/PGS": "PGS", "S_VOBSUB": "VobSub", "S_TEXT/UTF8": "SRT"}


def read_title(mkvmerge: str | None, p: Path) -> dict:
    """What MKVToolNix says about one file, in the shape of a MakeMKV title in disc_info.json."""
    t: dict = {"output_file": p.name, "size_bytes": p.stat().st_size, "streams": [], "chapters": 0,
               "duration_seconds": 0, "duration": ""}
    if not mkvmerge:
        return t
    try:
        r = subprocess.run([mkvmerge, "-J", str(p)], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=120, creationflags=NOWIN)
        info = json.loads(r.stdout or "{}")
    except Exception:
        return t
    secs = (info.get("container", {}).get("properties", {}).get("duration") or 0) / 1e9
    t.update(duration_seconds=int(round(secs)), duration=_hms(secs) if secs else "",
             chapters=sum(int(c.get("num_entries") or 0) for c in info.get("chapters") or []))
    title = info.get("container", {}).get("properties", {}).get("title")
    if title:
        t["name"] = title
    for tr in info.get("tracks") or []:
        pr = tr.get("properties") or {}
        kind = {"video": "Video", "audio": "Audio", "subtitles": "Subtitles"}.get(tr.get("type"))
        if not kind:
            continue
        s = {"type": kind, "lang3": pr.get("language") or "", "lang": pr.get("language") or "",
             "codec": CODECS.get(pr.get("codec_id") or "", tr.get("codec") or "")}
        if pr.get("track_name"):
            s["name"] = pr["track_name"]
        if kind == "Video" and pr.get("pixel_dimensions"):
            s["resolution"] = pr["pixel_dimensions"]
        if kind == "Audio":
            s["channels"] = int(pr.get("audio_channels") or 0)
            if pr.get("flag_commentary") or re.search(r"comment", pr.get("track_name") or "", re.I):
                s["flags"] = 1
        if kind == "Subtitles" and pr.get("forced_track"):
            s["forced"] = True
        t["streams"].append(s)
    return t


def describe(src: Path, mkvmerge: str | None) -> dict:
    """disc_info.json for a folder of videos (read before they're moved)."""
    used: set[int] = set()
    titles = []
    for i, p in enumerate(videos(src)):
        t = read_title(mkvmerge, p)
        t["title_id"] = _title_id(p, i, used)
        t["ripped"] = True
        titles.append(t)
    label = label_for(src.name)
    return {"name": label, "volume_label": label, "disc_label": label, "titles": titles,
            "imported_from": str(src), "ripped_at": dt.datetime.now().isoformat(timespec="seconds"),
            "status": "ok", "titles_saved": len(titles), "titles_failed": 0}


def label_for(name: str) -> str:
    """A disc label from a folder name, without what a search would trip on: "Inception (2010)
    {tmdb-27205} [1080p]" -> "Inception", "Inception.2010.1080p.BluRay" -> "Inception". A MakeMKV
    folder name ("THE_SANTA_CLAUSE_2") is kept as it is."""
    s = re.sub(r"\{[^}]*\}|\[[^\]]*\]", " ", name)
    s = re.sub(r"\((?:19|20)\d{2}\)", " ", s)
    if " " not in s.strip():  # "Blade.Runner.2049.2017.1080p": the last year and everything after it
        s = re.sub(r"^(.+)[._-](?:19|20)\d{2}(?=[._-]|$).*$", r"\1", s)
    s = re.sub(r"(?i)\b(?:2160p|1080p|720p|480p|4k|uhd|bluray|blu-ray|bdrip|remux|dvdrip|x264|x265|hevc)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" ._-")
    return s or name


def same_drive(a: Path, b: Path) -> bool:
    try:
        return os.stat(a).st_dev == os.stat(b).st_dev
    except OSError:
        return False


def run(src: Path, rip_root: Path, cfg: dict, log=print, on_done=None) -> Path:
    """Import src into a new folder in rip_root. Moves the files on the same drive, else copies
    them (the originals stay). disc_info.json is written last, so the folder isn't named while
    files are still arriving. Returns the new folder."""
    import rip_all
    import split
    job = JOBS.setdefault(str(src), {})
    mkvmerge = split.tool(cfg, "mkvmerge")
    if not mkvmerge:
        log(f"Import {src.name}: MKVToolNix not found, so lengths and tracks can't be read; naming will be rougher")
    info = describe(src, mkvmerge)
    dest = rip_root / f"{rip_all.safe_folder_name(info['disc_label'])}__import-{dt.datetime.now():%Y%m%d-%H%M%S}"
    dest.mkdir(parents=True)
    move = same_drive(src, rip_root)
    files = videos(src)
    job.update(state="running", folder=dest.name, done=0, total=sum(p.stat().st_size for p in files), moved=move)
    log(f"Import {src.name}: {'moving' if move else 'copying'} {len(files)} video(s) into {dest}")
    for p in files:
        target = dest / p.name
        if move:
            os.replace(p, target)
        else:
            shutil.copy2(p, target)
        job["done"] += target.stat().st_size
    (dest / "disc_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    job["state"] = "naming"
    log(f"Import {src.name}: done, naming it for review")
    if on_done:
        on_done(dest)
    job["state"] = "named"
    return dest


def start(src: Path, rip_root: Path, cfg: dict, log=print, on_done=None) -> dict:
    """Run an import in the background. Returns its job (state running / error)."""
    key = str(src)
    with LOCK:
        if JOBS.get(key, {}).get("state") == "running":
            return JOBS[key]
        JOBS[key] = {"state": "running", "done": 0, "total": 0, "folder": ""}

    def work():
        try:
            run(src, rip_root, cfg, log, on_done)
        except Exception as exc:
            JOBS[key].update(state="error", error=str(exc))
            log(f"Import {src.name} failed: {exc}")
    threading.Thread(target=work, daemon=True).start()
    return JOBS[key]
