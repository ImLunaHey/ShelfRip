"""
handbrake.py - optional: re-encode files with HandBrake, using one of your saved presets, as
they're filed into the library.

Off unless you turn it on (Settings > HandBrake). Shelfrip's own output is a straight copy of
the disc (a remux: no quality lost, every track kept); this trades that for smaller files.

    HandBrakeCLI --preset-import-file <your presets.json> -Z "<preset>" -i <rip> -o <encoded>

HandBrake's presets pick only some audio and subtitle tracks (often just the first of each),
so unless you turn it off, Shelfrip also asks for every audio and subtitle track, encoded the
way the preset's first audio track is: commentaries and other languages aren't lost.

The encode is written next to the rip (in _handbrake), then moved into the library like any
other file. The original stays in the rip folder until the whole disc is filed.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PROGRESS = re.compile(r"Encoding: task \d+ of \d+, (\d+(?:\.\d+)?) %")
INSTALL_DIRS = [Path(r"C:\Program Files\HandBrake"), Path(r"C:\Program Files\HandBrakeCLI"),
                Path(r"C:\Program Files (x86)\HandBrake")]


class Stopped(Exception):
    """The filing was stopped while HandBrake was encoding."""


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("handbrake_enabled"))


def applies(cfg: dict, item: dict) -> bool:
    """Is this title encoded? Movies and episodes always (when it's on); special features only
    if you chose everything."""
    if not enabled(cfg):
        return False
    if str(cfg.get("handbrake_scope") or "main") == "all":
        return True
    return item.get("role") in ("main", "episode")


def cli(cfg: dict) -> str | None:
    """HandBrakeCLI: your setting (the file or its folder), the usual install folders, then PATH.
    HandBrake's app doesn't include it: it's a separate download from handbrake.fr."""
    own = str(cfg.get("handbrake_cli") or "").strip().strip('"')
    cands = []
    if own:
        p = Path(own)
        cands += [p] if p.is_file() else [p / "HandBrakeCLI.exe", p / "HandBrakeCLI"]
    for d in INSTALL_DIRS:
        cands.append(d / "HandBrakeCLI.exe")
    for c in cands:
        if c.is_file():
            return str(c)
    return shutil.which("HandBrakeCLI")


def preset_file(cfg: dict) -> Path | None:
    """Your presets: the file you set, else the HandBrake app's own list of your presets."""
    own = str(cfg.get("handbrake_preset_file") or "").strip().strip('"')
    if own:
        return Path(own)
    appdata = os.environ.get("APPDATA")
    if appdata and (Path(appdata) / "HandBrake" / "presets.json").is_file():
        return Path(appdata) / "HandBrake" / "presets.json"
    return None


def _walk(presets: list) -> list[dict]:
    out = []
    for p in presets or []:
        if p.get("Folder"):
            out += _walk(p.get("ChildrenArray") or [])
        elif p.get("PresetName"):
            out.append(p)
    return out


def presets(cfg: dict) -> list[dict]:
    """The presets in your file (folders flattened). [] if there's no file or it can't be read."""
    f = preset_file(cfg)
    try:
        return _walk(json.loads(f.read_text(encoding="utf-8")).get("PresetList") or []) if f else []
    except (OSError, ValueError, AttributeError):
        return []


def preset(cfg: dict) -> dict | None:
    name = str(cfg.get("handbrake_preset") or "").strip()
    return next((p for p in presets(cfg) if p.get("PresetName") == name), None)


def extension(cfg: dict) -> str:
    """'.mp4' if the preset makes MP4s, else '.mkv'."""
    p = preset(cfg) or {}
    return ".mp4" if "mp4" in str(p.get("FileFormat") or "").lower() else ".mkv"


def problem(cfg: dict) -> str:
    """'' if HandBrake is ready to use, else what's missing (shown before filing starts)."""
    if not enabled(cfg):
        return ""
    if not cli(cfg):
        return ("HandBrake is turned on in Settings, but HandBrakeCLI wasn't found. It's a separate download "
                "from handbrake.fr (the command line version); set its location in Settings > HandBrake.")
    f = preset_file(cfg)
    if not f or not f.is_file():
        return ("HandBrake is turned on, but there's no presets file. In HandBrake, export your preset "
                "(Presets > Export), then choose that file in Settings > HandBrake.")
    if not str(cfg.get("handbrake_preset") or "").strip():
        return "HandBrake is turned on, but no preset is chosen. Pick one in Settings > HandBrake."
    if not preset(cfg):
        names = ", ".join(p["PresetName"] for p in presets(cfg)[:8])
        return (f"HandBrake preset \"{cfg.get('handbrake_preset')}\" isn't in {f.name}"
                + (f" (it has: {names})." if names else "."))
    return ""


def command(cfg: dict, src: Path, out: Path) -> list[str]:
    p = preset(cfg) or {}
    cmd = [cli(cfg) or "HandBrakeCLI", "--preset-import-file", str(preset_file(cfg)), "-Z", p.get("PresetName", ""),
           "-i", str(src), "-o", str(out)]
    if cfg.get("handbrake_keep_tracks", True):  # every audio and subtitle track, not just the preset's picks
        cmd += ["--all-audio", "--audio-lang-list", "any", "--all-subtitles", "--subtitle-lang-list", "any"]
        first = (p.get("AudioList") or [{}])[0]
        if first.get("AudioEncoder"):  # the extra tracks are encoded like the preset's first track
            cmd += ["-E", first["AudioEncoder"]]
            if first.get("AudioMixdown"):
                cmd += ["-6", first["AudioMixdown"]]
            if first.get("AudioBitrate") and not first.get("AudioTrackQualityEnable"):
                cmd += ["-B", str(first["AudioBitrate"])]
    return cmd


def encode(src: Path, out: Path, cfg: dict, on_progress=None, stopped=None) -> None:
    """Encode src to out with your preset. on_progress(fraction 0-1) as it goes; stopped() -> True
    makes it give up (the half-made file is removed). Raises with HandBrake's last words if it fails."""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.stem + ".encoding" + out.suffix)
    tmp.unlink(missing_ok=True)
    proc = subprocess.Popen(command(cfg, src, tmp), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            creationflags=NOWIN)
    tail: list[str] = []
    buf = b""
    gave_up = []

    def watch() -> None:  # stop even while HandBrake prints nothing (it can sit quietly scanning a disc image)
        while proc.poll() is None:
            if stopped and stopped():
                gave_up.append(1)
                proc.kill()
                return
            time.sleep(0.5)
    if stopped:
        threading.Thread(target=watch, daemon=True).start()

    def take(raw: bytes) -> None:
        line = raw.decode("utf-8", "replace").strip()
        m = PROGRESS.search(line)
        if m:
            if on_progress:
                on_progress(min(1.0, float(m.group(1)) / 100))
        elif line:
            tail[:] = (tail + [line])[-6:]
    try:
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                take(buf)
                break
            buf += chunk
            *lines, buf = re.split(rb"[\r\n]", buf)
            for raw in lines:
                take(raw)
            if stopped and stopped():
                proc.kill()
                proc.wait()
                raise Stopped()
        code = proc.wait()
        proc.stdout.close()
        if gave_up:
            raise Stopped()
    except BaseException:
        proc.stdout.close()
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        time.sleep(0.2)  # let Windows let go of the file
        tmp.unlink(missing_ok=True)
        raise
    if code != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        why = next((t for t in reversed(tail) if re.search(r"error|fail|invalid|not found|no title", t, re.I)),
                   tail[-1] if tail else f"exit code {code}")
        raise RuntimeError(f"HandBrake couldn't encode {src.name}: {why}")
    os.replace(tmp, out)
