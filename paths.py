r"""
paths.py - where Shelfrip keeps its files.

  APP_DIR   the program: the .py files, review.html and tools\ (next to Shelfrip.exe).
  DATA_DIR  your own files: config.json, disc_catalog.db, learned_labels.json and the
            .cache folder. %APPDATA%\Shelfrip on Windows, so the program folder can be
            replaced by an update (or live in Program Files) without losing anything.

Put an empty file called portable.txt next to the program to keep your files in the
program folder instead (for a copy on a USB stick). SHELFRIP_DATA overrides both.

First start after updating from a version that kept config.json next to the scripts:
the files are copied (not moved) to DATA_DIR, and the old copies are left where they were.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "Shelfrip"
APP_VERSION = "0.9.0"
# Shown to the web services the app talks to (MusicBrainz asks every app for one).
APP_URL = "https://github.com/VandykeConnor/ShelfRip"
USER_AGENT = f"Shelfrip/{APP_VERSION} ( {APP_URL} )"
# GitHub repository ("owner/name") whose Releases hold new versions. Empty = don't check for updates.
UPDATE_REPO = "VandykeConnor/ShelfRip"
# The shared Shelfrip disc database (server/ in the repository). Empty = off. "community_url" in config.json overrides it.
COMMUNITY_URL = "https://shelfrip-db.shelfrip.workers.dev"

APP_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent


def _data_dir() -> Path:
    if os.environ.get("SHELFRIP_DATA") or os.environ.get("DISC_RIPPER_DATA"):
        return Path(os.environ.get("SHELFRIP_DATA") or os.environ["DISC_RIPPER_DATA"]).expanduser()
    if (APP_DIR / "portable.txt").exists():
        return APP_DIR
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / APP_NAME
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "shelfrip"


DATA_DIR = _data_dir()
CONFIG_PATH = DATA_DIR / "config.json"
CACHE_DIR = DATA_DIR / ".cache"

# Files an older version kept next to the scripts.
_OLD_FILES = ("config.json", "disc_catalog.db", "learned_labels.json")

# Settings whose defaults changed when the app became shareable. A config made before then
# didn't store them, because the old defaults were right for it: write the old values in,
# so an existing setup keeps behaving exactly as it did.
_OLD_DEFAULTS = {
    "output_root": r"E:\Ripped",
    "plex_library_root": r"N:\Media Library",
    "media_server": "plex",
    "format_folders": True,
    "movie_format_folders": {"4k": "4K Blu-Ray", "bluray": "Blu-Ray", "dvd": "DVD"},
    "tv_format_folders": {"4k": "4K Blu Ray", "bluray": "Blu-Ray", "dvd": "DVD"},
    "use_dvdcompare": True,
    "job_total_discs": 400,
}


def _old_data_dir() -> Path | None:
    """Where the app kept your files while it was called Disc Ripper (before 2026-11-18)."""
    if os.environ.get("DISC_RIPPER_DATA") or DATA_DIR == APP_DIR:
        return None
    if os.name == "nt":
        return Path(os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")) / "Disc Ripper"
    return Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")) / "disc-ripper"


def migrate() -> str:
    """Copy an older version's files into DATA_DIR once. Returns a line for the log, or ''."""
    old = _old_data_dir()
    if old and not CONFIG_PATH.exists() and (old / "config.json").exists():
        shutil.copytree(old, DATA_DIR, dirs_exist_ok=True)
        return f"Copied your settings from {old} to {DATA_DIR} (the app is called Shelfrip now)."
    if DATA_DIR == APP_DIR or CONFIG_PATH.exists() or not (APP_DIR / "config.json").exists():
        return ""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    for name in _OLD_FILES:
        src = APP_DIR / name
        if src.exists():
            shutil.copy2(src, DATA_DIR / name)
    if (APP_DIR / ".cache").is_dir() and not CACHE_DIR.exists():
        shutil.copytree(APP_DIR / ".cache", CACHE_DIR)
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))
        for k, v in _OLD_DEFAULTS.items():
            cfg.setdefault(k, v)
        cfg["migrated_from"] = str(APP_DIR)
        CONFIG_PATH.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    except (OSError, ValueError):
        pass
    return f"Moved your settings and disc database to {DATA_DIR} (the old copies in {APP_DIR} are no longer used)."


MIGRATION_NOTE = ""
try:
    MIGRATION_NOTE = migrate()
except OSError as exc:
    MIGRATION_NOTE = f"Couldn't copy your settings to {DATA_DIR}: {exc}"
try:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
except OSError:
    pass
