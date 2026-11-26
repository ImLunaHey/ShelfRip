"""
discs.py - rebuild a filed disc as a fresh rip, and name it the way Shelfrip would today.

Shared by record.py (on a PC with internet, to make the fixtures) and test_naming.py (on
GitHub, to check nothing changed).
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"

# Settings left out of the fixtures: where things are, keys, Plex, notifications and your
# install id. Everything else is kept, as any of it might change how a disc is named.
PRIVATE = ("root", "path", "dir", "key", "token", "secret", "password", "notify", "plex_url", "install_id",
           "migrated_from", "offsets")
HAS_KEYS = ("tmdb_api_key", "omdb_api_key")  # whether one was set changes which services are asked

# What a test compares: the parts of a plan you'd see on the Review tab.
PLAN_KEYS = ("kind", "title", "year", "tmdb_id", "season", "format", "library_dir", "match_source")
ITEM_KEYS = ("source", "role", "action", "category", "name", "dest_dir", "episode", "episodes", "attach",
             "attach_to", "needs_split")


def fixture_config(cfg: dict) -> dict:
    out = {k: v for k, v in cfg.items() if not any(p in k.lower() for p in PRIVATE)}
    for k in HAS_KEYS:
        out[k] = "test-key" if str(cfg.get(k) or "").strip() and "paste" not in str(cfg.get(k)) else ""
    return out


def setup_env(cfg_extra: dict) -> Path:
    """A throwaway data folder and rip folder, before Shelfrip's modules are imported."""
    tmp = Path(tempfile.mkdtemp(prefix="shelfrip-test-"))
    (tmp / "data").mkdir()
    (tmp / "rip").mkdir()
    cfg = {"shared_tmdb": False, **cfg_extra, "output_root": str(tmp / "rip"), "plex_library_root": str(tmp / "lib"),
           "share_discs": False, "auto_file": False}
    (tmp / "data" / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    os.environ["SHELFRIP_DATA"] = str(tmp / "data")
    sys.path.insert(0, str(HERE.parent))
    return tmp


def lay_out(fix: Path, rip: Path) -> Path:
    """The disc folder as it was right after ripping: its records, and an empty file per ripped title."""
    meta = json.loads((fix / "fixture.json").read_text(encoding="utf-8"))
    folder = rip / meta["folder"]
    if folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    for name in ("disc_info.json", "makemkv_info.txt"):
        if (fix / name).exists():
            shutil.copy2(fix / name, folder / name)
    info = json.loads((folder / "disc_info.json").read_text(encoding="utf-8"))
    for t in info.get("titles", []):
        if t.get("output_file"):
            p = folder / t["output_file"]
            p.parent.mkdir(parents=True, exist_ok=True)
            p.touch()
    return folder


def name_disc(folder: Path, rip: Path, key: str) -> dict:
    import identify
    cfg = identify.load_config()
    tmdb = identify.TMDB(key) if cfg.get("tmdb_api_key") else None
    plan = identify.plan_folder(folder, rip, tmdb, {"movies": [], "shows": []}, cfg)
    return summary(plan or {})


def summary(plan: dict) -> dict:
    out = {k: plan.get(k) for k in PLAN_KEYS if plan.get(k) is not None}
    out["items"] = [{k: it[k] for k in ITEM_KEYS if it.get(k) not in (None, "", [], False)}
                    for it in plan.get("items", [])]
    return out
