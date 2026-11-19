r"""
tidy.py - keeps the rip folder from filling up with leftovers.

It looks for:
  * failed attempts: a disc folder with no video in it (MakeMKV couldn't read the disc, or
    the window was closed while it was still reading). If that disc was never ripped
    after all, it says so, so you know to put it back in the pile.
  * extra copies: a second rip of a disc that's already filed, or two unfinished rips of
    the same disc (the most complete one is kept). Discs are compared by their titles'
    lengths and sizes, not just their names, since two different discs can share a label.
  * skipped clips that older versions left in _Filed.
  * lock files left by a rip that's no longer running.

Nothing is deleted until you press "Clean up" on the Home tab, and anything touched in the
last 30 minutes (a rip that's still going) is left alone.
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

import rip_all

QUIET = 30 * 60  # a folder changed more recently than this may still be in use


def _newest(d: Path) -> float:
    try:
        return max([d.stat().st_mtime] + [f.stat().st_mtime for f in d.rglob("*")])
    except OSError:
        return time.time()


def _size(d: Path) -> int:
    total = 0
    for f in d.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total


def _videos(d: Path) -> list[Path]:
    return [*d.glob("*.mkv"), *d.glob("rip/*.flac"), *d.glob("rip/*.wav")]


def _signature(d: Path) -> tuple:
    """The disc's titles (length and size), from MakeMKV's scan saved when the rip started."""
    try:
        info = (d / "makemkv_info.txt").read_text(encoding="utf-8", errors="replace")
        titles = rip_all.parse_disc_info(info)["titles"]
    except Exception:
        return ()
    return tuple(sorted((int(t.get("duration_seconds") or 0), int(t.get("size_bytes") or 0)) for t in titles))


def _label(d: Path) -> str:
    return d.name.rsplit("__", 1)[0]


def _waiting(d: Path) -> bool:
    """Named and waiting for review (or being filed): never offered for deletion here."""
    return (d / "plan.json").exists()


def scan(root: Path, busy_labels: set[str] = frozenset()) -> dict:
    """Everything that could go. Each item: id (path relative to the rip folder), kind, bytes, why."""
    items: list[dict] = []
    if not root.is_dir():
        return {"items": [], "bytes": 0}
    now = time.time()
    filed_dir = root / "_Filed"
    filed = [d for d in filed_dir.iterdir() if d.is_dir()] if filed_dir.is_dir() else []
    filed_labels = {_label(d).lower() for d in filed}
    filed_sigs = {s for s in (_signature(d) for d in filed) if s}
    busy = {rip_all.safe_folder_name(b).lower() for b in busy_labels}

    discs = []
    for d in sorted(root.iterdir()):
        if not d.is_dir() or d.name.startswith(("_", ".")) or "__" not in d.name:
            continue
        if _waiting(d) or now - _newest(d) < QUIET:
            continue
        discs.append(d)

    # failed attempts: no video at all
    rest = []
    for d in discs:
        if _videos(d):
            rest.append(d)
            continue
        label = _label(d)
        if label.lower() in busy:
            continue  # this disc is in a drive being ripped right now
        never = label.lower() not in filed_labels and not any(
            _label(o).lower() == label.lower() and _videos(o) for o in discs if o != d)
        items.append({"id": d.name, "kind": "failed", "bytes": _size(d), "label": label,
                      "why": "A rip that didn't get going (no video in it)." +
                             (" This disc hasn't been ripped yet." if never else ""),
                      "never_ripped": never})

    # extra copies of the same disc
    groups: dict[tuple, list[Path]] = {}
    for d in rest:
        sig = _signature(d)
        if sig:
            groups.setdefault(sig, []).append(d)
    for sig, ds in groups.items():
        if sig in filed_sigs:
            for d in ds:
                items.append({"id": d.name, "kind": "duplicate", "bytes": _size(d), "label": _label(d),
                              "why": "Another copy of a disc you've already filed."})
            continue
        if len(ds) > 1:
            def rank(d):  # finished rip first, then the one with the most video
                return ((d / "disc_info.json").exists(), sum(f.stat().st_size for f in _videos(d)), d.name)
            keep = max(ds, key=rank)
            for d in ds:
                if d != keep:
                    items.append({"id": d.name, "kind": "duplicate", "bytes": _size(d), "label": _label(d),
                                  "why": f"An unfinished copy of the same disc as {keep.name}, which has more of it."})

    # clips older versions left in _Filed
    for d in filed:
        clips = [f for f in d.glob("*.mkv")]
        if clips:
            items.append({"id": f"_Filed/{d.name}/*.mkv", "kind": "clips", "label": _label(d),
                          "bytes": sum(f.stat().st_size for f in clips),
                          "why": f"{len(clips)} clip(s) you chose not to keep. The disc's records stay."})

    # lock files from rips that aren't running
    for f in root.glob(".ripping_*.lock"):
        try:
            if now - f.stat().st_mtime > rip_all.LOCK_STALE:
                items.append({"id": f.name, "kind": "lock", "bytes": f.stat().st_size, "label": "",
                              "why": "Left behind by a rip that's no longer running."})
        except OSError:
            pass
    return {"items": items, "bytes": sum(i["bytes"] for i in items),
            "never_ripped": sorted({i["label"] for i in items if i.get("never_ripped")})}


def clean(root: Path, ids: list[str], busy_labels: set[str] = frozenset()) -> dict:
    """Delete the chosen items, checking each one again first."""
    still = {i["id"]: i for i in scan(root, busy_labels)["items"]}
    freed, done, skipped = 0, [], []
    for i in ids:
        item = still.get(i)
        if not item:
            skipped.append(i)
            continue
        try:
            if item["kind"] == "clips":
                folder = root / "_Filed" / i.split("/")[1]
                for f in folder.glob("*.mkv"):
                    f.unlink()
            elif item["kind"] == "lock":
                (root / i).unlink()
            else:
                target = (root / i).resolve()
                if target.parent != root.resolve():
                    skipped.append(i)
                    continue
                shutil.rmtree(target)
            freed += item["bytes"]
            done.append(i)
        except OSError:
            skipped.append(i)
    return {"freed": freed, "done": done, "skipped": skipped}
