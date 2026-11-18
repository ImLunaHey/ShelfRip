r"""
split.py - cut a video that holds several episodes into one file per episode (step 2b).

Uses MKVToolNix (mkvextract to read chapter times, mkvmerge to cut). Nothing is
re-encoded: mkvmerge copies the streams and cuts on the nearest keyframe, which on
discs is almost always exactly at a chapter mark.

A split is described by chapter numbers, so it's easy to fix on the review page:

    split = {
      "chapters": [0.0, 95.2, 1402.7, ...],  # start time of each chapter, seconds
      "total": 4210.5,                       # length of the whole video
      "starts": [1, 9, 17],                  # chapter index where each episode's own part begins
      "opening": 1,                          # how many chapters at the very start are the opening
      "ending": 1,                           # how many chapters at the very end are the ending
      "copy_opening": true,                  # put the opening onto every episode
      "copy_ending": true,                   # put the ending onto every episode
    }

Only the Python standard library is used.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SHORT = 150      # an opening/ending chapter is at most this long (seconds)
SAME = 6         # two chapters "match" if their lengths differ by at most this (seconds)
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------- tools

HERE = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
BUNDLED = HERE / "tools" / "mkvtoolnix"   # portable MKVToolNix shipped with the app
MKVTOOLNIX_URL = "https://mkvtoolnix.download/downloads.html#windows"


def tool_dirs(cfg: dict) -> list[Path]:
    """Where to look for MKVToolNix: your setting, the bundled copy, then the usual install folders."""
    dirs = [Path(d) for d in (cfg.get("mkvtoolnix_dir"),) if d]
    dirs += [BUNDLED, Path(r"C:\Program Files\MKVToolNix"), Path(r"C:\Program Files (x86)\MKVToolNix")]
    return dirs


def tool(cfg: dict, name: str) -> str | None:
    for d in tool_dirs(cfg):
        for cand in (d / f"{name}.exe", d / name):
            if cand.is_file():
                return str(cand)
    return shutil.which(name)


def available(cfg: dict) -> bool:
    return bool(tool(cfg, "mkvmerge") and tool(cfg, "mkvextract"))


def read_chapters(path: Path, cfg: dict) -> tuple[list[float], float]:
    """(chapter start times, total length) in seconds."""
    mkvmerge, mkvextract = tool(cfg, "mkvmerge"), tool(cfg, "mkvextract")
    info = json.loads(subprocess.run([mkvmerge, "-J", str(path)], capture_output=True, text=True,
                                     encoding="utf-8", errors="replace", creationflags=NOWIN).stdout or "{}")
    total = (info.get("container", {}).get("properties", {}).get("duration") or 0) / 1e9
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "chapters.txt"
        subprocess.run([mkvextract, str(path), "chapters", "--simple", str(out)],
                       capture_output=True, creationflags=NOWIN)
        text = out.read_text(encoding="utf-8", errors="replace") if out.exists() else ""
    starts = []
    for m in re.finditer(r"^CHAPTER\d+=(\d+):(\d+):(\d+(?:\.\d+)?)\s*$", text, re.M):
        h, mi, s = m.groups()
        starts.append(int(h) * 3600 + int(mi) * 60 + float(s))
    starts = sorted(set(round(x, 3) for x in starts if x < total - 1)) if total else sorted(set(starts))
    if not starts or starts[0] > 0.5:
        starts.insert(0, 0.0)
    return starts, total


# --------------------------------------------------------------------------- proposing

def _len(ch: list[float], total: float, i: int) -> float:
    return (ch[i + 1] if i + 1 < len(ch) else total) - ch[i]


def propose(chapters: list[float], total: float, count: int) -> dict:
    """Guess where each of `count` episodes starts, and whether to copy an opening/ending."""
    n = len(chapters)
    split = {"chapters": chapters, "total": total, "opening": 0, "ending": 0,
             "copy_opening": False, "copy_ending": False, "starts": [], "confidence": "low"}
    if count < 2 or n < count:
        split["starts"] = [0]
        return split
    op = 1 if n > count and _len(chapters, total, 0) <= SHORT else 0
    en = 1 if n > count + op and _len(chapters, total, n - 1) <= SHORT else 0
    body_from = chapters[op]
    body_to = chapters[n - en] if en else total
    target = (body_to - body_from) / count

    # episode i starts at the chapter boundary nearest body_from + i*target
    starts = [op]
    for i in range(1, count):
        want = body_from + i * target
        cands = [j for j in range(starts[-1] + 1, n - en - (count - 1 - i)) if j > starts[-1]]
        if not cands:
            break
        starts.append(min(cands, key=lambda j: abs(chapters[j] - want)))
    if len(starts) < count:
        split["starts"] = list(range(min(count, n)))
        return split

    # Does each episode already carry its own opening/ending? Then don't copy.
    op_len = _len(chapters, total, 0) if op else 0
    en_len = _len(chapters, total, n - 1) if en else 0
    op_repeats = op and all(abs(_len(chapters, total, s) - op_len) <= SAME for s in starts[1:])
    en_repeats = en and all(abs(_len(chapters, total, s - 1) - en_len) <= SAME for s in starts[1:])
    if op_repeats:
        op, starts[0] = 0, 0          # each episode has its own opening: plain cuts
    if en_repeats:
        en = 0
    split.update(opening=op, ending=en, copy_opening=bool(op), copy_ending=bool(en), starts=starts)

    # how evenly do the cuts fall? (a guide for the review page)
    lens = [r[-1][1] - r[0][0] for r in (episode_ranges(split, i) for i in range(count))]
    spread = (max(lens) - min(lens)) / max(1, sum(lens) / len(lens))
    split["confidence"] = "high" if spread <= 0.12 else "medium" if spread <= 0.3 else "low"
    return split


def propose_from_segments(chapters: list[float], total: float, segments: str) -> dict | None:
    """Use MakeMKV's segment map (e.g. '1-7,8-14,15-21,50') when it divides the video by chapter.

    On many DVDs each episode is its own run of chapters, so each run is an episode. Runs
    shorter than 90 s (a logo, a 'to be continued' card) are joined to the run before."""
    n = len(chapters)
    runs = []
    for part in (segments or "").replace(" ", "").split(","):
        m = re.fullmatch(r"(\d+)(?:-(\d+))?", part)
        if not m:
            return None
        a, b = int(m.group(1)), int(m.group(2) or m.group(1))
        runs.append((a - 1, b - 1))
    if len(runs) < 2 or runs[0][0] != 0 or runs[-1][1] != n - 1 or \
            any(r[0] != p[1] + 1 for p, r in zip(runs, runs[1:])):
        return None  # not a plain chapter map
    t = lambda j: chapters[j] if j < n else total
    starts = []
    for a, b in runs:
        if starts and t(b + 1) - t(a) < 90:
            continue
        starts.append(a)
    if len(starts) < 2:
        return None
    split = {"chapters": chapters, "total": total, "opening": 0, "ending": 0,
             "copy_opening": False, "copy_ending": False, "starts": starts, "confidence": "high",
             "from": "disc layout"}
    # one opening at the very start, not repeated at each episode: copy it onto every episode
    op_len = _len(chapters, total, 0)
    if op_len <= SHORT and starts[1] > 1 and not all(abs(_len(chapters, total, s) - op_len) <= SAME
                                                     for s in starts[1:]):
        split.update(opening=1, copy_opening=True)
        split["starts"][0] = 1
    return split


def episode_ranges(split: dict, i: int) -> list[tuple[float, float]]:
    """Time ranges (seconds) that make up episode i, in play order."""
    ch, total = split["chapters"], split["total"]
    n, starts = len(ch), split["starts"]
    op = int(split.get("opening") or 0) if split.get("copy_opening") else 0
    en = int(split.get("ending") or 0) if split.get("copy_ending") else 0
    t = lambda j: ch[j] if j < n else total
    a = 0 if i == 0 and not op else starts[i]
    b = starts[i + 1] if i + 1 < len(starts) else n - en
    ranges = []
    if op and starts[i] >= op:
        ranges.append((t(0), t(op)))
    ranges.append((t(a), t(b)))
    if en:
        ranges.append((t(n - en), total))
    merged: list[tuple[float, float]] = []
    for x, y in ranges:
        if y - x < 0.05:
            continue
        if merged and abs(merged[-1][1] - x) < 0.05:
            merged[-1] = (merged[-1][0], y)
        else:
            merged.append((x, y))
    return merged


def describe(split: dict) -> list[str]:
    out = []
    for i in range(len(split["starts"])):
        parts = [f"{_ts(a)}-{_ts(b)}" for a, b in episode_ranges(split, i)]
        out.append(" + ".join(parts))
    return out


# --------------------------------------------------------------------------- audio track names

def tag_audio(path: Path, audio: list[dict], cfg: dict) -> str:
    """Name the commentary tracks in a file (and mark them as commentary). '' when done or
    nothing to do, else why it was skipped. Nothing is re-encoded; only track names change."""
    want = [a for a in audio or [] if a.get("commentary") and (a.get("name") or "").strip()]
    if not want:
        return ""
    mkvmerge, prop = tool(cfg, "mkvmerge"), tool(cfg, "mkvpropedit")
    if not (mkvmerge and prop):
        return "MKVToolNix not found, so commentary tracks weren't named"
    info = json.loads(subprocess.run([mkvmerge, "-J", str(path)], capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", creationflags=NOWIN).stdout or "{}")
    tracks = [t for t in info.get("tracks", []) if t.get("type") == "audio"]
    if len(tracks) != len(audio):
        return f"the file has {len(tracks)} audio tracks but the disc listed {len(audio)}, so commentary names were left alone"
    for t, a in zip(tracks, audio):
        lang = (t.get("properties") or {}).get("language") or ""
        if a.get("lang") and lang and lang not in ("und", a["lang"]):
            return "the audio tracks don't line up with the disc's list, so commentary names were left alone"
    def edits(with_flag: bool) -> list[str]:
        out = []
        for a in want:
            out += ["--edit", f"track:a{a['i']}", "--set", f"name={a['name'].strip()}"]
            if with_flag:
                out += ["--set", "flag-commentary=1"]
        return out
    for with_flag in (True, False):  # older MKVToolNix doesn't know flag-commentary: set just the names
        r = subprocess.run([prop, str(path)] + edits(with_flag), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", creationflags=NOWIN)
        if r.returncode == 0:
            return ""
    return "couldn't name the commentary tracks"


LANG_ALIASES = {"en": "eng", "english": "eng", "es": "spa", "spanish": "spa", "fr": "fre", "fra": "fre",
                "french": "fre", "de": "ger", "deu": "ger", "german": "ger", "it": "ita", "ja": "jpn",
                "jp": "jpn", "japanese": "jpn", "pt": "por", "zh": "chi", "zho": "chi", "ko": "kor", "nl": "dut",
                "nld": "dut"}


def _lang(code: str) -> str:
    c = (code or "").strip().lower()
    return LANG_ALIASES.get(c, c)


def is_forced(t: dict) -> bool:
    p = t.get("properties") or {}
    return bool(p.get("forced_track")) or "forced" in (p.get("track_name") or "").lower()


def set_default_tracks(path: Path, cfg: dict) -> str:
    """Make your language's main audio track the default, flag forced subtitles (only the
    foreign-dialogue lines) so players show them automatically, and optionally turn on full
    subtitles in a language you pick. '' when done or nothing to do, else why it was skipped."""
    want_audio = _lang(cfg.get("audio_language") or "eng")
    want_subs = _lang(cfg.get("subtitle_language") or "")
    forced_on = cfg.get("forced_subtitles", True)
    mkvmerge, prop = tool(cfg, "mkvmerge"), tool(cfg, "mkvpropedit")
    if not (mkvmerge and prop):
        return "MKVToolNix not found, so default tracks weren't set"
    info = json.loads(subprocess.run([mkvmerge, "-J", str(path)], capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", creationflags=NOWIN).stdout or "{}")
    tracks = info.get("tracks", [])
    lang = lambda t: _lang((t.get("properties") or {}).get("language") or "")
    commentary = lambda t: bool((t.get("properties") or {}).get("flag_commentary")) or \
        "comment" in ((t.get("properties") or {}).get("track_name") or "").lower()
    audio = [t for t in tracks if t.get("type") == "audio"]
    subs = [t for t in tracks if t.get("type") == "subtitles"]
    main = next((t for t in audio if lang(t) == want_audio and not commentary(t)), None)
    edits = []
    num = lambda t: (t.get("properties") or {}).get("number") or (t["id"] + 1)
    if main:
        for t in audio:
            edits += ["--edit", f"track:@{num(t)}", "--set", f"flag-default={1 if t is main else 0}"]
    spoken = lang(main) if main else (lang(audio[0]) if audio else want_audio)
    forced = next((t for t in subs if is_forced(t) and lang(t) == spoken), None) if forced_on else None
    full = next((t for t in subs if not is_forced(t) and lang(t) == want_subs), None) if want_subs else None
    for t in subs:
        on = t is forced or t is full
        edits += ["--edit", f"track:@{num(t)}", "--set", f"flag-default={1 if on else 0}"]
        if t is forced:
            edits += ["--set", "flag-forced=1"]
    if not edits:
        return ""
    r = subprocess.run([prop, str(path)] + edits, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=NOWIN)
    return "" if r.returncode == 0 else "couldn't set the default audio and subtitle tracks"


# --------------------------------------------------------------------------- cutting

def episode_chapters(split: dict, ranges: list[tuple[float, float]]) -> list[float]:
    """Chapter start times within the cut episode (seconds from its start), first one at 0."""
    out, offset = [], 0.0
    for a, b in ranges:
        for c in [a] + [c for c in split["chapters"] if a < c < b - 1]:
            x = round(offset + c - a, 3)
            if not out or x - out[-1] > 1:
                out.append(x)
        offset += b - a
    return out


def renumber_chapters(path: Path, split: dict, ranges: list[tuple[float, float]], cfg: dict) -> None:
    """Replace the cut file's chapters with ones numbered from 1 (Chapter 01, 02, ...)."""
    prop = tool(cfg, "mkvpropedit")
    if not prop:
        return
    times = episode_chapters(split, ranges)
    text = "".join(f"CHAPTER{k:02d}={_ts(x)}\nCHAPTER{k:02d}NAME=Chapter {k:02d}\n"
                   for k, x in enumerate(times, 1))
    ch = path.with_name("chapters.txt")
    ch.write_text(text, encoding="utf-8")
    subprocess.run([prop, str(path), "--chapters", str(ch)], capture_output=True, creationflags=NOWIN)
    ch.unlink(missing_ok=True)


def _ts(sec: float) -> str:
    sec = max(0.0, sec)
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h):02d}:{int(m):02d}:{s:06.3f}"


def cut(src: Path, split: dict, i: int, out: Path, cfg: dict, title: str = "") -> Path:
    """Write episode i of src to out (via a temp folder next to out). Returns out."""
    mkvmerge = tool(cfg, "mkvmerge")
    if not mkvmerge:
        raise RuntimeError("MKVToolNix (mkvmerge) not found. Set mkvtoolnix_dir in config.json.")
    ranges = episode_ranges(split, i)
    parts = ",".join(("+" if k else "") + f"{_ts(a)}-{_ts(b)}" for k, (a, b) in enumerate(ranges))
    out.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="split_", dir=str(out.parent)))
    try:
        cmd = [mkvmerge, "-o", str(work / "episode.mkv"), "--split", f"parts:{parts}"]
        if title:
            cmd += ["--title", title]
        cmd.append(str(src))
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           creationflags=NOWIN)
        made = sorted(work.glob("*.mkv"))
        if r.returncode >= 2 or len(made) != 1:
            last = ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[-1:]
            raise RuntimeError(f"mkvmerge couldn't cut episode {i + 1}" + (f": {last[0]}" if last else ""))
        # sanity check: the result should be about as long as the ranges asked for
        want = sum(b - a for a, b in ranges)
        info = json.loads(subprocess.run([mkvmerge, "-J", str(made[0])], capture_output=True, text=True,
                                         encoding="utf-8", errors="replace", creationflags=NOWIN).stdout or "{}")
        got = (info.get("container", {}).get("properties", {}).get("duration") or 0) / 1e9
        if got and abs(got - want) > max(5, 0.03 * want):
            raise RuntimeError(f"episode {i + 1} came out {got:.0f}s long, expected {want:.0f}s")
        renumber_chapters(made[0], split, ranges, cfg)
        os.replace(made[0], out)
        return out
    finally:
        shutil.rmtree(work, ignore_errors=True)
