r"""
app.py - Shelfrip: one app for ripping, naming, reviewing and filing.

Double-click Shelfrip.exe (installed), or "Disc Ripper.bat" in a copy run from the scripts. It opens one
page in your browser
(http://localhost:8765, only reachable from this PC) with three tabs:

  Drives    what's in each drive and how far each rip has got. Auto-rip rips every disc
            as soon as you insert it; "Rip loaded discs now" rips what's in the drives once.
  Review    the review page: check names, then file into Plex. New rips are named here
            automatically as soon as they finish.
  Settings  folders, MakeMKV/MKVToolNix locations, Plex address, and your keys (keys are
            never shown, only whether they're set).

Keep the app's window open while it works (it's minimized to the taskbar). Use Quit on the
page, or close that window, to stop it.

Only the Python standard library is used.
"""

from __future__ import annotations

import json
from pathlib import Path
import os
import socket
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import ThreadingHTTPServer

import desktop
import progress  # noqa: F401  (bundled into the exe)
import identify
import naming
import paths
import review
import rip_all

JOB_DEFAULTS = {"auto_file": True, "auto_file_minutes": 15, "audio_language": "eng", "subtitle_language": "",
                "forced_subtitles": True, "retry_failed_titles": True, "job_total_discs": 0,
                "min_free_gb_rips": 60, "app_window": True, "tray_icon": True}
SECRETS = ("tmdb_api_key", "omdb_api_key", "plex_token")
SETTINGS = [  # (key, label, kind)
    ("output_root", "Rip folder (where discs are ripped to before review)", "text"),
    ("plex_library_root", "Media library folder (holds your Movies and TV Shows folders)", "text"),
    ("media_server", "Media server (decides how files are named)", "select"),
    ("format_folders", "Separate folders per format (Movies\\Blu-Ray\\..., Movies\\DVD\\...)", "bool"),
    ("use_dvdcompare", "Also look up extras names on DVDCompare (reads its web pages)", "bool"),
    ("use_community", "Look discs up in the shared Shelfrip disc database", "bool"),
    ("share_discs", "Share what I file with the Shelfrip disc database (anonymous: disc fingerprint, title lengths and names only)", "bool"),
    ("makemkvcon_path", "MakeMKV (makemkvcon64.exe)", "text"),
    ("mkvtoolnix_dir", "MKVToolNix folder", "text"),
    ("plex_url", "Plex address (Plex only, optional: lets the app check what Plex matched)", "text"),
    ("music_library_root", "Music library folder (empty = Music inside the Plex library folder)", "text"),
    ("cyanrip_path", "cyanrip for music CDs (empty = tools\\cyanrip\\cyanrip.exe)", "text"),
    ("cd_offsets", "CD drive read offsets, e.g. D:6, E:667 (for AccurateRip)", "text"),
    ("music_lyrics", "Save lyrics next to music tracks (.lrc / .txt, from LRCLIB)", "bool"),
    ("min_length_seconds", "Skip titles shorter than (seconds)", "number"),
    ("skip_extras_under_seconds", "Set extras shorter than this to Skip (seconds)", "number"),
    ("watch_poll_seconds", "Check drives every (seconds)", "number"),
    ("eject_after_filing", "Eject each disc once you've filed (or discarded) it", "bool"),
    ("eject_when_done", "Eject each disc as soon as its rip finishes instead", "bool"),
    ("check_plex_before_rip", "Don't rip discs your library already has in the same or better quality", "bool"),
    ("notifications", "Windows notifications when a rip finishes", "bool"),
    ("phone_notify_url", "Phone alerts: ntfy.sh topic address (optional, e.g. https://ntfy.sh/your-topic)", "text"),
    ("auto_rip", "Turn auto-rip on when the app opens", "bool"),
    ("auto_file", "File discs automatically when everything matched with confidence", "bool"),
    ("auto_file_minutes", "…after waiting this many minutes (so you can step in)", "number"),
    ("audio_language", "Default audio language (e.g. eng, jpn)", "text"),
    ("subtitle_language", "Turn on full subtitles in this language (empty = off)", "text"),
    ("forced_subtitles", "Show forced subtitles (foreign-dialogue lines) automatically", "bool"),
    ("retry_failed_titles", "Retry titles that hit read errors once", "bool"),
    ("job_total_discs", "Discs you plan to rip, for a progress bar (0 = no goal)", "number"),
    ("min_free_gb_rips", "Don't start a rip with less than this free in the rip folder (GB)", "number"),
    ("tmdb_api_key", "TMDB key", "secret"),
    ("omdb_api_key", "OMDb key", "secret"),
    ("plex_token", "Plex token (Plex only, optional)", "secret"),
    ("check_updates", "Tell me when a new version of Shelfrip is out", "bool"),
    ("app_window", "Open Shelfrip in its own window (not a browser tab)", "bool"),
    ("tray_icon", "Keep Shelfrip running by the clock when its window is closed (Quit from the icon's menu)", "bool"),
]
CHOICES = {"media_server": [{"value": k, "label": v} for k, v in naming.SERVERS.items()]}


# --------------------------------------------------------------------------- alerts

def notify(title: str, text: str) -> None:
    """A Windows notification (and, if set, a phone push via ntfy.sh or similar). Never blocks."""
    cfg = _read_config()
    if not cfg.get("notifications", True):
        return

    def run():
        if TRAY and TRAY.notify(title, text):
            pass
        elif os.name == "nt":
            esc = lambda x: str(x).replace("'", "''").replace("&", "and").replace("<", "").replace(">", "")
            ps = (
                "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null;"
                "$x = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                f"$t = $x.GetElementsByTagName('text'); $t.Item(0).AppendChild($x.CreateTextNode('{esc(title)}')) > $null;"
                f"$t.Item(1).AppendChild($x.CreateTextNode('{esc(text)}')) > $null;"
                "$n = [Windows.UI.Notifications.ToastNotification]::new($x);"
                "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
                "'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe').Show($n)")
            try:
                import subprocess
                subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except Exception:
                pass
        url = (cfg.get("phone_notify_url") or "").strip()
        if url.startswith("https://"):
            try:
                req = urllib.request.Request(url, data=text.encode("utf-8"), method="POST",
                                             headers={"Title": title.encode("ascii", "ignore").decode()})
                urllib.request.urlopen(req, timeout=15).close()
            except Exception:
                pass
    threading.Thread(target=run, daemon=True).start()


# --------------------------------------------------------------------------- before ripping

def disc_kind(root: str) -> str:
    """'dvd', 'bluray' or '4k' from the disc's folders (UHD discs use index.bdmv version 0300)."""
    from pathlib import Path as _P
    try:
        idx = _P(root) / "BDMV" / "index.bdmv"
        if idx.is_file():
            return "4k" if idx.read_bytes()[:8] == b"INDX0300" else "bluray"
        if (_P(root) / "VIDEO_TS").is_dir():
            return "dvd"
    except OSError:
        pass
    return ""


def identify_disc(dev: str, label: str, cfg: dict) -> dict | None:
    """What a disc is, before ripping it: from your catalog or TheDiscDB (by fingerprint), else
    from a label you've filed before. {kind, title, year, tmdb_id, episodes: [(season, ep)], how}"""
    import catalog
    import discdb
    fp = discdb.fingerprint(dev + "\\") if len(dev) == 2 and dev[1] == ":" else None
    h = (fp or {}).get("content_hash")
    if h and catalog.DB_PATH.exists():
        con = catalog.connect()
        try:
            row = con.execute("SELECT * FROM discs WHERE content_hash = ? ORDER BY filed_at DESC LIMIT 1", (h,)).fetchone()
            if row:
                eps = [(r["season"], e) for r in con.execute(
                    "SELECT * FROM titles WHERE disc_id = ? AND kept = 1 AND role = 'episode'", (row["id"],))
                    for e in range(r["episode"], (r["episode_last"] or r["episode"]) + 1) if r["episode"] is not None]
                return {"kind": row["kind"], "title": row["title"], "year": row["year"], "tmdb_id": row["tmdb_id"],
                        "episodes": eps, "how": "your catalog"}
        finally:
            con.close()
    if h and cfg.get("use_thediscdb", True):
        try:
            for item in discdb._query(discdb.Q_HASH, {"h": h}, f"tdbhash:{h}"):
                for rel in item.get("releases") or []:
                    for d in rel.get("discs") or []:
                        if (d.get("contentHash") or "").upper() != h:
                            continue
                        kind = "tv" if (item.get("type") or "").lower() in ("series", "tv", "show") else "movie"
                        eps = [(int(t["season"]), int(t["episode"])) for t in d.get("titles") or []
                               if (t.get("itemType") or "").lower() == "episode"
                               and str(t.get("season")).isdigit() and str(t.get("episode")).isdigit()]
                        return {"kind": kind, "title": item.get("title"), "year": str(item.get("year") or ""),
                                "tmdb_id": str((item.get("externalids") or {}).get("tmdb") or ""),
                                "episodes": eps, "how": "TheDiscDB"}
        except Exception:
            pass
    prev = discdb.learned(label)
    if prev and prev.get("kind") == "movie" and prev.get("tmdb_id"):
        return {"kind": "movie", "title": prev.get("title"), "year": str(prev.get("year") or ""),
                "tmdb_id": str(prev["tmdb_id"]), "episodes": [], "how": "a label you've filed before"}
    return None


def in_plex_already(dev: str, label: str, cfg: dict, ident: dict | None = None) -> str:
    """A sentence saying Plex already has this disc in the same or better quality, else ''."""
    kind = disc_kind(dev + "\\")
    ident = ident if ident is not None else identify_disc(dev, label, cfg)
    if not ident or not kind:
        return ""
    full = {**identify.DEFAULTS, **cfg}
    fmt = (full["tv_format_folders"] if ident["kind"] == "tv" else full["movie_format_folders"]).get(kind, "")
    plan = {"kind": ident["kind"], "title": ident["title"], "year": ident["year"], "tmdb_id": ident["tmdb_id"],
            "format": fmt, "items": []}
    if ident["kind"] == "tv":
        if not ident["episodes"]:
            return ""
        plan["items"] = [{"source": f"{s}x{e}", "role": "episode", "season": s, "episodes": [e]}
                         for s, e in ident["episodes"]]
    else:
        plan["items"] = [{"source": "main", "role": "main", "name": ""}]
    mine = identify.quality_rank(fmt, full)
    copies = identify.library_copies(plan, review.library(), full)
    have = [max(c, key=lambda h: h["rank"]) for c in copies.values()]
    if not mine or len(copies) < len(plan["items"]) or any(h["rank"] < mine for h in have):
        return ""
    best = max(have, key=lambda h: h["rank"])
    what = f"{ident['title']}" + (f" ({ident['year']})" if ident.get("year") else "")
    if ident["kind"] == "tv":
        eps = sorted(ident["episodes"])
        what += f" s{eps[0][0]:02d}e{eps[0][1]:02d}-e{eps[-1][1]:02d}"
    return (f"Plex already has {what} as {best['format']}"
            f"{' (better quality)' if best['rank'] > mine else ''}, so it wasn't ripped "
            f"(recognised from {ident['how']}).")


# --------------------------------------------------------------------------- ripping

class Ripper:
    """Watches the drives and runs rips (the same code as rip_all.py --watch)."""

    def __init__(self) -> None:
        self.cfg: dict | None = None
        self.error = ""
        self.drives: list[dict] = []
        self.busy: set[str] = set()
        self.finished: dict[str, str] = {}
        self.wake = threading.Event()
        self.rip_once = False
        self.force: set[str] = set()
        self.held: dict[str, str] = {}   # device -> label held back because Plex has it
        self.match: dict[str, dict] = {}  # device -> what its disc was recognised as before ripping
        raw = _read_config()
        self.auto = bool(raw.get("auto_rip", False))
        rip_all.ON_DONE.append(self.after_rip)
        rip_all.ON_LOW_SPACE.append(lambda why: notify("Rip folder is full", why))
        threading.Thread(target=self.loop, daemon=True).start()

    def load(self) -> None:
        try:
            self.cfg = rip_all.load_config(exit_on_error=False)
            self.error = ""
            from pathlib import Path
            rip_all.LOG_FILE = Path(self.cfg["output_root"]) / "disc_ripper.log"
        except rip_all.SetupError as exc:
            self.cfg, self.error = None, str(exc)
        except Exception as exc:
            self.cfg, self.error = None, f"Couldn't read the settings: {exc}"

    def loop(self) -> None:
        while True:
            self.load()
            if self.cfg:
                try:
                    os.makedirs(self.cfg["output_root"], exist_ok=True)
                    drives = rip_all.scan_drives(self.cfg)
                    for d in drives:
                        d["locked_elsewhere"] = (d["device"] not in self.busy and d["loaded"]
                                                 and rip_all.drive_locked(self.cfg, d["device"]))
                    self.drives = drives
                    try:
                        for t in review.auto_file_tick(log=rip_all.log):
                            notify("Filed automatically", f"{t} matched with confidence and is being filed into your library.")
                    except Exception as exc:
                        rip_all.log(f"auto-file check failed: {exc}")
                    if self.auto or self.rip_once:
                        self.rip_once = False
                        force, self.force = self.force, set()
                        rip_all.rip_loaded(self.cfg, self.busy, self.finished, notify_locked=False,
                                           force=force, skip=self.check_first)
                except Exception as exc:
                    self.error = f"Couldn't check the drives: {exc}"
            poll = int((self.cfg or {}).get("watch_poll_seconds") or 15)
            self.wake.wait(max(5, poll))
            self.wake.clear()

    def check_first(self, d: dict) -> bool:
        """Before ripping: hold the disc back if Plex already has it (same or better quality)."""
        ident = None if d.get("audio") else self.recognise(d)
        if not self.cfg.get("check_plex_before_rip", True):
            return False
        if d.get("audio"):  # music CD: filed before (by its disc id)?
            import music
            try:
                why = music.in_library(d, {**identify.DEFAULTS, **self.cfg})
            except Exception as exc:
                rip_all.log(f"{d['device']} [{d['disc_label']}] couldn't check the music library first ({exc})")
                why = ""
            if why:
                self.finished[d["device"]] = d["disc_label"]
                self.held[d["device"]] = d["disc_label"]
                rip_all.STATUS[d["device"]] = {"label": d["disc_label"], "state": "in_plex", "message": why}
                rip_all.log(f"{d['device']} [{d['disc_label']}] {why}")
                notify("Already in Plex", f"{why} Swap the disc, or click Rip anyway.")
            return bool(why)
        try:
            why = in_plex_already(d["device"], d["disc_label"], self.cfg, ident=ident)
        except Exception as exc:
            rip_all.log(f"{d['device']} [{d['disc_label']}] couldn't check Plex first ({exc})")
            return False
        if why:
            self.finished[d["device"]] = d["disc_label"]
            self.held[d["device"]] = d["disc_label"]
            rip_all.STATUS[d["device"]] = {"label": d["disc_label"], "state": "in_plex", "message": why}
            rip_all.log(f"{d['device']} [{d['disc_label']}] {why}")
            notify("Already in Plex", f"{d['disc_label']}: {why} Swap the disc, or click Rip anyway.")
            return True
        return False

    def recognise(self, d: dict) -> dict | None:
        """What the disc in this drive is (before ripping), remembered so the page can show its box art."""
        try:
            ident = identify_disc(d["device"], d["disc_label"], self.cfg)
        except Exception:
            ident = None
        if ident:
            eps = ident.get("episodes") or []
            self.match[d["device"]] = {"label": d["disc_label"], "kind": ident["kind"], "title": ident.get("title") or "",
                                       "year": ident.get("year") or "", "tmdb_id": ident.get("tmdb_id") or "",
                                       "season": eps[0][0] if eps else None, "how": ident.get("how") or ""}
        return ident or {}  # {} = looked, not recognised (in_plex_already won't look again)

    def after_rip(self, disc: dict, out_dir) -> None:
        """Name the new rip straight away so it's waiting on the Review tab."""
        if not disc:
            return
        label, dev = disc.get("disc_label"), disc.get("drive")
        try:
            n = review.plan_new_folders()
            rip_all.log(f"{label}: named, ready to review" if n else f"{label}: ripped")
        except Exception as exc:
            rip_all.log(f"{label}: couldn't name it ({exc})")
        ok = disc.get("status") == "ok"
        notify(f"{dev} finished" if ok else f"{dev} needs a look",
               f"{label} is ripped and waiting in Review. Check the names, then file it to eject the disc."
               if ok else f"{label} finished with problems ({disc.get('titles_failed', 0)} titles failed).")

    def state(self) -> dict:
        drives = []
        for d in self.drives:
            st = dict(rip_all.STATUS.get(d["device"], {}))
            st.pop("cancel", None)
            ripping = d["device"] in self.busy
            if not ripping and st.get("state") in ("scanning", "ripping"):
                st["state"] = "idle"
            drives.append({"device": d["device"], "loaded": d["loaded"], "label": d["disc_label"],
                           "ripping": ripping, "elsewhere": d.get("locked_elsewhere", False),
                           "already": self.finished.get(d["device"]) == d["disc_label"] and not ripping,
                           **{k: v for k, v in st.items() if k != "label"},
                           "rip_label": st.get("label", "")})
        try:
            plans = review.list_plans()
        except Exception:
            plans = []
        waiting = len(plans)
        by_disc = {p.get("disc_label"): p for p in plans}
        for d in drives:  # what's in each drive, for its box art
            p = by_disc.get(d["label"]) if d["label"] else None
            m = self.match.get(d["device"])
            if p and p.get("kind") in ("movie", "tv", "music"):
                d["match"] = {"kind": p["kind"], "title": p.get("album") if p["kind"] == "music" else p.get("title"),
                              "year": p.get("year") or "", "tmdb_id": str(p.get("tmdb_id") or ""),
                              "season": p.get("season"), "folder": p["folder"], "how": "named for review"}
            elif m and m.get("label") == d["label"]:
                d["match"] = m
        try:
            setup = setup_check()
        except Exception:
            setup = []
        active = rips_in_progress(review.RIP_ROOT)
        by_label = {a["label"]: a for a in active}
        for d in drives:  # attach folder-based progress (and speed / time left) to each drive
            a = by_label.get(rip_all.safe_folder_name(d["label"] or ""))
            if a and (d["ripping"] or d["elsewhere"]):
                d["progress"] = a
        try:
            stats = job_stats(waiting, len(self.busy))
        except Exception as exc:
            stats = {"error": str(exc)}
        filing = sum(1 for jb in review.JOBS.values() if jb.get("state") == "running")
        return {"auto": self.auto, "error": self.error, "drives": drives, "stats": stats, "filing": filing, "waiting": waiting, "setup": setup, "active": active,
                "log": list(rip_all.LOG_LINES)[-40:]}


RIPPER: Ripper | None = None
TRAY: "desktop.Tray | None" = None


def tray_status() -> str:
    """One line for the tray icon: what the drives are doing and what's waiting."""
    if not RIPPER:
        return "Shelfrip"
    parts = []
    for d in RIPPER.drives:
        st = rip_all.STATUS.get(d["device"], {})
        if d["device"] in RIPPER.busy:
            pct = st.get("pct")
            parts.append(f"{d['device']} ripping" + (f" {pct}%" if pct else ""))
    try:
        n = len(review.list_plans())
    except Exception:
        n = 0
    if n:
        parts.append(f"{n} to review")
    return " · ".join(parts) or ("Auto-rip on, waiting for a disc" if RIPPER.auto else "Idle")


def quit_app(ask: bool = True) -> None:
    running = sorted(RIPPER.busy) if RIPPER else []
    running += [k for k, j in review.JOBS.items() if j.get("state") == "running"]
    if running and ask and os.name == "nt":
        import ctypes
        u32 = ctypes.WinDLL("user32")
        u32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint]
        if u32.MessageBoxW(None, f"Still working on: {', '.join(running)}.\n\nQuitting stops it (a rip is cut off and "
                           "starts again next time). Quit anyway?", "Quit Shelfrip", 0x4 | 0x30 | 0x40000) != 6:
            return  # MB_YESNO | MB_ICONWARNING | MB_TOPMOST; 6 = Yes
    if TRAY:
        TRAY.remove()
    os._exit(0)


def start_tray(url: str, use_window: bool) -> None:
    global TRAY
    shown = {"console": False}

    def toggle_auto():
        RIPPER.auto = not RIPPER.auto
        rip_all.log("Auto-rip on: insert discs any time" if RIPPER.auto else "Auto-rip off")
        RIPPER.wake.set()

    def toggle_console():
        shown["console"] = not shown["console"]
        desktop.show_console(shown["console"])

    def menu():
        try:
            n = len(review.list_plans())
        except Exception:
            n = 0
        items = [(f"Shelfrip: {tray_status()}", None), None,
                 ("Open Shelfrip", lambda: desktop.open_window(url, use_window))]
        if n:
            items.append((f"Review {n} disc{'s' if n != 1 else ''}", lambda: desktop.open_window(url + "#review", use_window)))
        items.append(("Pause auto-rip" if RIPPER and RIPPER.auto else "Turn auto-rip on", toggle_auto))
        if console:
            items.append(("Hide log window" if shown["console"] else "Show log window", toggle_console))
        elif desktop.LOG_PATH.exists():
            items.append(("Open the log", lambda: desktop.open_file(desktop.LOG_PATH)))
        items += [None, ("Quit Shelfrip", quit_app)]
        return items

    console = desktop.owns_console()
    tray = desktop.Tray("Shelfrip", lambda: desktop.open_window(url, use_window), menu)
    if not tray.start():
        return
    TRAY = tray
    if console:
        desktop.show_console(False)  # the tray icon is the way back in now

    def keep_tip_fresh():
        while True:
            time.sleep(10)
            try:
                tray.set_tip(f"Shelfrip: {tray_status()}")
            except Exception:
                pass
    threading.Thread(target=keep_tip_fresh, daemon=True).start()
_STATS: dict = {"t": 0.0, "filed": {}}


def job_stats(waiting: int, ripping: int) -> dict:
    """Progress through the whole job, free space, and discs that had read errors."""
    import shutil
    from pathlib import Path
    cfg = {**rip_all.DEFAULT_CONFIG, **identify.DEFAULTS, **JOB_DEFAULTS, **_read_config()}
    root = Path(cfg["output_root"])
    if time.time() - _STATS["t"] > 60:  # reading every filed plan is cheap, but not every 2 seconds
        filed = {"discs": 0, "movies": 0, "tv": 0, "music": 0, "hours": 0.0, "today": 0}
        today = time.strftime("%Y-%m-%d")
        for pj in (root / "_Filed").glob("*/plan.json"):
            try:
                plan = json.loads(pj.read_text(encoding="utf-8"))
            except Exception:
                continue
            if plan.get("status") != "filed":
                continue
            filed["discs"] += 1
            kind = {"movie": "movies", "tv": "tv", "music": "music"}.get(plan.get("kind"), "movies")
            filed[kind] += 1
            filed["hours"] += sum(float(it.get("duration_seconds") or 0) for it in plan.get("items", [])
                                  if it.get("action") == "move") / 3600
            filed["today"] += str(plan.get("filed_at", "")).startswith(today)
        filed["hours"] = round(filed["hours"], 1)
        _STATS.update(t=time.time(), filed=filed)
    space = []
    for name, path, need in (("Rip folder", cfg["output_root"], float(cfg.get("min_free_gb_rips") or 60)),
                             ("Library", cfg["plex_library_root"], 100.0)):
        try:
            du = shutil.disk_usage(path)
            space.append({"name": name, "path": path, "free_gb": round(du.free / 1e9), "total_gb": round(du.total / 1e9),
                          "low": du.free / 1e9 < need})
        except OSError:
            space.append({"name": name, "path": path, "free_gb": None, "total_gb": None, "low": False})
    try:
        damaged = json.loads((root / rip_all.DAMAGED).read_text(encoding="utf-8"))[-20:][::-1]
    except Exception:
        damaged = []
    return {**_STATS["filed"], "total": int(cfg.get("job_total_discs") or 0), "waiting": waiting,
            "ripping": ripping, "space": space, "damaged": damaged}


def dismiss_damaged(label: str) -> None:
    from pathlib import Path
    p = Path({**rip_all.DEFAULT_CONFIG, **_read_config()}["output_root"]) / rip_all.DAMAGED
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
        p.write_text(json.dumps([r for r in rows if r.get("label") != label], indent=2), encoding="utf-8")
    except Exception:
        pass
_RATE: dict[str, tuple[float, int, float]] = {}   # folder -> (time, bytes, bytes per second)


def rips_in_progress(root) -> list[dict]:
    """Every rip being written right now, from this app or any other Rip window.

    Progress = bytes written so far / the sizes MakeMKV listed for the titles it's ripping."""
    import re as _re
    out, now = [], time.time()
    try:
        folders = [d for d in root.iterdir() if d.is_dir() and not d.name.startswith("_")
                   and not (d / "disc_info.json").exists() and (d / "makemkv_info.txt").exists()]
    except OSError:
        return out
    for d in folders:
        try:
            files = [f for f in d.iterdir() if f.suffix.lower() == ".mkv"]
            done = sum(f.stat().st_size for f in files)
            newest = max([f.stat().st_mtime for f in files] + [(d / "makemkv_info.txt").stat().st_mtime])
            if now - newest > 600:  # nothing written for 10 min: not running (cancelled or crashed)
                continue
            info = (d / "makemkv_info.txt").read_text(encoding="utf-8", errors="replace")
            total = sum(int(m) for m in _re.findall(r'^TINFO:\d+,11,0,"(\d+)"', info, _re.M))
            n_titles = len(_re.findall(r'^TINFO:\d+,27,0,', info, _re.M))
        except (OSError, ValueError):
            continue
        prev = _RATE.get(d.name)
        rate = prev[2] if prev else 0.0
        if prev and now - prev[0] >= 5:
            inst = (done - prev[1]) / (now - prev[0])
            rate = inst if not prev[2] else 0.7 * prev[2] + 0.3 * inst
            _RATE[d.name] = (now, done, rate)
        elif not prev:
            _RATE[d.name] = (now, done, 0.0)
        pct = min(99, int(100 * done / total)) if total else 0
        eta = int((total - done) / rate) if rate > 0 and total > done else None
        out.append({"folder": d.name, "label": d.name.rsplit("__", 1)[0], "pct": pct, "done": done,
                    "total": total, "titles_done": len(files), "titles": n_titles,
                    "mb_s": round(rate / 1e6, 1) if rate else 0, "eta_s": eta})
    return out


def setup_check() -> list[dict]:
    """What the app needs, whether it's there, and where to get it if not."""
    import split
    cfg = {**rip_all.DEFAULT_CONFIG, **identify.DEFAULTS, **_read_config()}
    out = []
    for key, name, what in (("output_root", "Rip folder", "where discs are ripped to before review"),
                            ("plex_library_root", "Media library folder", "the folder holding your Movies and TV Shows folders")):
        p = str(cfg.get(key) or "").strip()
        ok = bool(p) and (os.path.isdir(p) or (key == "output_root" and os.path.isdir(os.path.dirname(p.rstrip("\\/")) or "")))
        out.append({"name": name, "ok": ok, "required": True, "link": "",
                    "detail": p if ok else (f"{p} doesn't exist (or isn't connected)" if p else f"not chosen yet: {what}")})
    mk = rip_all.find_makemkv(cfg)
    out.append({"name": "MakeMKV", "ok": bool(mk), "detail": mk or "not installed: needed to rip discs",
                "link": "" if mk else rip_all.MAKEMKV_URL, "required": True})
    mm = split.tool(cfg, "mkvmerge")
    bundled = bool(mm) and str(split.BUNDLED).lower() in mm.lower()
    out.append({"name": "MKVToolNix", "ok": bool(mm),
                "detail": (("bundled copy: " if bundled else "") + os.path.dirname(mm)) if mm else
                          f"not found: needed to split episodes. Install it, or put the portable version in {split.BUNDLED}",
                "link": "" if mm else split.MKVTOOLNIX_URL, "required": False})
    key = str(cfg.get("tmdb_api_key") or "")
    out.append({"name": "TMDB key", "ok": bool(key) and "paste" not in key,
                "detail": "set" if key and "paste" not in key else "not set: needed to name movies and episodes (add it in Settings)",
                "link": "" if key and "paste" not in key else "https://www.themoviedb.org/settings/api", "required": True})
    import music
    cy = music.find_cyanrip(cfg)
    out.append({"name": "cyanrip (music CDs)", "ok": bool(cy),
                "detail": cy or f"not found: needed to rip music CDs. Put cyanrip.exe (cyanrip-win64.exe) in {music.BUNDLED}",
                "link": "" if cy else music.CYANRIP_URL, "required": False})
    mr = music.music_root(cfg)
    out.append({"name": "Music library folder", "ok": mr.is_dir(),
                "detail": str(mr) if mr.is_dir() else f"{mr} doesn't exist yet: it's created when you file your first CD. "
                          "Then add it to Plex as a Music library.",
                "link": "" if mr.is_dir() else "https://support.plex.tv/articles/200288926-creating-libraries/", "required": False})
    plex = bool(cfg.get("plex_url")) and bool(cfg.get("plex_token")) and "paste" not in str(cfg.get("plex_token")).lower()
    out.append({"name": "Plex check", "ok": plex, "detail": "on" if plex else "off (optional: add the Plex address and token in Settings)",
                "link": "" if plex else "https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/",
                "required": False})
    return out


# --------------------------------------------------------------------------- library report

REPORT: dict = {"state": "none"}


def build_report() -> None:
    """Episode gaps, titles owned in several formats, and what Plex hasn't matched right."""
    import re as _re
    REPORT.clear()
    REPORT.update(state="running", step="Reading the library folders")
    try:
        lib = review.library(refresh=True)
        cfg = review.CFG
        rank = lambda f: identify.quality_rank(f, cfg)
        # --- movies in more than one format
        movies: dict[str, list[dict]] = {}
        for m in lib["movies"]:
            key = f"tmdb-{m['id']}" if m["id_src"] == "tmdb" else f"{m['norm']}|{m['year']}"
            movies.setdefault(key, []).append(m)
        dup_movies = [{"title": v[0]["title"], "year": v[0]["year"],
                       "formats": sorted({x["format_folder"] for x in v}, key=rank, reverse=True)}
                      for v in movies.values() if len({x["format_folder"] for x in v}) > 1]
        # --- shows: episodes per season, across format folders
        shows: dict[str, dict] = {}
        for sh in lib["shows"]:
            key = f"tmdb-{sh['id']}" if sh["id_src"] == "tmdb" else sh["norm"]
            e = shows.setdefault(key, {"title": sh["title"], "year": sh["year"], "id": sh["id"] if sh["id_src"] == "tmdb" else "",
                                       "eps": {}, "formats": set()})
            e["formats"].add(sh["format_folder"])
            try:
                files = [f for f in sh["folder"].rglob("*") if f.suffix.lower() in identify.VIDEO_EXT]
            except OSError:
                files = []
            for f in files:
                m = _re.search(r"s(\d{1,2})e(\d{1,3})(?:-e(\d{1,3}))?", f.name, _re.I)
                if not m:
                    continue
                s_, a = int(m.group(1)), int(m.group(2))
                for ep in range(a, int(m.group(3) or a) + 1):
                    e["eps"].setdefault(s_, {}).setdefault(ep, set()).add(sh["format_folder"])
        REPORT["step"] = "Checking episode counts on TMDB"
        tv_rows = []
        for n, e in enumerate(sorted(shows.values(), key=lambda x: x["title"].lower()), 1):
            REPORT["step"] = f"Checking episode counts on TMDB ({n} of {len(shows)})"
            counts, firsts = {}, {}
            if review.TMDB and e["id"]:
                try:
                    for se in review.TMDB.tv(int(e["id"])).get("seasons") or []:
                        counts[se["season_number"]] = se.get("episode_count") or 0
                except Exception:
                    pass
            seasons = []
            for s_ in sorted(set(e["eps"]) | {k for k in counts if k > 0}):
                have = e["eps"].get(s_, {})
                nums = sorted(have)
                missing = [x for x in range(nums[0], nums[-1] + 1) if x not in have] if nums else []
                total = counts.get(s_)
                if total and nums and nums[0] == 1 and nums[-1] < total:   # numbered 1..N in TMDB
                    missing += list(range(nums[-1] + 1, total + 1))
                elif total and not nums:
                    missing = None   # whole season missing
                if s_ == 0:
                    missing = []  # specials are rarely all on disc; don't list gaps
                multi = sorted(x for x, f in have.items() if len(f) > 1)
                if s_ == 0 and not nums:
                    continue
                if missing or missing is None or multi:
                    seasons.append({"season": s_, "have": len(nums), "total": total, "missing": missing, "multi": multi})
            if seasons or len(e["formats"]) > 1:
                tv_rows.append({"title": e["title"], "year": e["year"], "formats": sorted(e["formats"], key=rank, reverse=True),
                                "seasons": seasons})
        REPORT["step"] = "Asking Plex what it matched"
        try:
            import plex
            audit = plex.audit(cfg)
        except Exception as exc:
            audit = {"error": str(exc)}
        REPORT.update(state="done", built=time.strftime("%Y-%m-%d %H:%M"), dup_movies=dup_movies, tv=tv_rows,
                      plex=audit, counts={"movies": len(movies), "shows": len(shows)})
    except Exception as exc:
        REPORT.update(state="error", error=str(exc))


# --------------------------------------------------------------------------- updates

UPDATE: dict = {"app": paths.APP_NAME, "current": paths.APP_VERSION}


def _ver(v: str) -> tuple:
    return tuple(int(x) for x in __import__("re").findall(r"\d+", v)[:3])


def check_update() -> None:
    """Ask GitHub once, at start, whether there's a newer release. Never blocks or fails loudly."""
    if not paths.UPDATE_REPO or not _read_config().get("check_updates", True):
        return
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{paths.UPDATE_REPO}/releases/latest",
                                     headers={"User-Agent": paths.USER_AGENT, "Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=15) as r:
            rel = json.loads(r.read().decode("utf-8"))
        tag = str(rel.get("tag_name") or "")
        if tag and _ver(tag) > _ver(paths.APP_VERSION):
            UPDATE.update(latest=tag.lstrip("v"), url=rel.get("html_url") or "")
    except Exception:
        pass


# --------------------------------------------------------------------------- settings

def _read_config() -> dict:
    try:
        return json.loads(identify.CONFIG_PATH.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}


def settings_view() -> dict:
    raw = _read_config()
    merged = {"check_plex_before_rip": True, "notifications": True, "check_updates": True, **JOB_DEFAULTS}
    merged.update(rip_all.DEFAULT_CONFIG)
    merged.update(identify.DEFAULTS)
    merged.update(raw)
    out = []
    for key, label, kind in SETTINGS:
        v = merged.get(key, "")
        if kind == "secret":  # never send a key back to the page
            v = bool(v) and "paste" not in str(v).lower()
        row = {"key": key, "label": label, "kind": kind, "value": v}
        if kind == "select":
            row["choices"] = CHOICES.get(key, [])
        out.append(row)
    return {"settings": out, "path": str(identify.CONFIG_PATH), "setup": setup_check(), "version": UPDATE,
            "first_run": not raw.get("setup_done") and not raw.get("migrated_from")}


def save_settings(values: dict) -> None:
    raw = _read_config()
    if values.get("setup_done"):
        raw["setup_done"] = True
    kinds = {k: kind for k, _, kind in SETTINGS}
    for key, v in values.items():
        kind = kinds.get(key)
        if not kind:
            continue
        if kind == "secret":
            if isinstance(v, str) and v.strip():  # empty = keep the current key
                raw[key] = v.strip()
            elif v is None:
                raw[key] = ""
            continue
        if kind == "number":
            try:
                v = int(v)
            except (TypeError, ValueError):
                continue
        elif kind == "bool":
            v = bool(v)
        elif kind == "select":
            v = str(v)
            if v not in {c["value"] for c in CHOICES.get(key, [])}:
                continue
        else:
            v = str(v).strip()
        raw[key] = v
    identify.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = identify.CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    tmp.replace(identify.CONFIG_PATH)
    review.reload_config()
    if RIPPER:
        RIPPER.wake.set()


# --------------------------------------------------------------------------- web

class Handler(review.Handler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        try:
            if u.path == "/api/drives":
                return self.send(200, RIPPER.state())
            if u.path == "/api/settings":
                return self.send(200, settings_view())
            if u.path == "/api/report":
                return self.send(200, REPORT)
            if u.path == "/api/version":
                return self.send(200, UPDATE)
            if u.path == "/api/progress":
                import progress
                cfg = {**rip_all.DEFAULT_CONFIG, **JOB_DEFAULTS, **_read_config()}
                if not cfg.get("output_root"):
                    return self.send(200, {"none": True})
                return self.send(200, progress.compute(Path(cfg["output_root"]), int(cfg.get("job_total_discs") or 0)))
        except Exception as exc:
            return self.send(500, {"error": str(exc)})
        return super().do_GET()

    def do_POST(self):
        if self.headers.get("Origin") not in (None, f"http://localhost:{review.PORT}",
                                              f"http://127.0.0.1:{review.PORT}"):
            return self.send(403, {"error": "forbidden"})
        u = urllib.parse.urlparse(self.path)
        if u.path == "/api/report":
            if REPORT.get("state") != "running":
                threading.Thread(target=build_report, daemon=True).start()
                REPORT.update(state="running", step="Starting")
            return self.send(200, REPORT)
        if u.path == "/api/pick":  # the Browse buttons on the Settings page
            b = self.body()
            got = desktop.pick("file" if b.get("kind") == "file" else "folder", str(b.get("start") or ""), str(b.get("title") or ""))
            return self.send(200, {"path": got, "available": got is not None})
        if u.path not in ("/api/rip", "/api/settings", "/api/quit"):
            return super().do_POST()
        try:
            b = self.body()
            if u.path == "/api/rip" and b.get("action") == "dismiss_damaged":
                dismiss_damaged(str(b.get("label") or ""))
                return self.send(200, {"ok": True})
            if u.path == "/api/rip":
                act = b.get("action")
                if act in ("auto_on", "auto_off"):
                    RIPPER.auto = act == "auto_on"
                    rip_all.log("Auto-rip on: insert discs any time" if RIPPER.auto else "Auto-rip off")
                elif act == "rip_now":
                    RIPPER.rip_once = True
                elif act == "cancel":
                    if not rip_all.cancel(str(b.get("device") or "")):
                        return self.send(200, {"error": "That drive isn't ripping."})
                elif act == "eject":
                    dev = str(b.get("device") or "")
                    if dev in RIPPER.busy:
                        return self.send(200, {"error": "That drive is ripping. Cancel it first."})
                    rip_all.eject(dev)
                elif act == "rip_again":  # rip anyway (already ripped, or already in Plex)
                    dev = str(b.get("device") or "")
                    RIPPER.finished.pop(dev, None)
                    RIPPER.held.pop(dev, None)
                    RIPPER.force.add(dev)
                    RIPPER.rip_once = True
                RIPPER.wake.set()
                return self.send(200, {"ok": True, **RIPPER.state()})
            if u.path == "/api/settings":
                save_settings(b.get("values") or {})
                return self.send(200, {"ok": True, **settings_view()})
            if u.path == "/api/quit":
                running = sorted(RIPPER.busy) + [k for k, j in review.JOBS.items() if j.get("state") == "running"]
                if running and not b.get("force"):
                    return self.send(200, {"busy": running})
                self.send(200, {"ok": True})
                threading.Timer(0.5, lambda: quit_app(ask=False)).start()
                return
        except Exception as exc:
            return self.send(500, {"error": str(exc)})


class Server(ThreadingHTTPServer):
    # Python lets a server share a port that's already in use (SO_REUSEADDR). On Windows that means
    # Shelfrip could start on a port another program is using, and the browser would get that
    # program's answer instead (an "Unsupported method ('GET')" page). Take the port for ourselves.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _is_shelfrip(port: int) -> bool:
    """Is Shelfrip itself already answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/version", timeout=2) as r:
            info = json.loads(r.read().decode("utf-8"))
        return info.get("app") == paths.APP_NAME or ("current" in info and "app" not in info)
    except Exception:
        return False


def _port_taken(port: int) -> bool:
    """Is anything listening on this port, on 127.0.0.1 or ::1 ("localhost" can mean either)?"""
    for fam, host in ((socket.AF_INET, "127.0.0.1"), (getattr(socket, "AF_INET6", None), "::1")):
        if fam is None:
            continue
        try:
            with socket.socket(fam, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    return False


def open_server() -> tuple[Server | None, int]:
    """Start the web server on 8765, or the next free port if another program has it.
    Returns (None, port) when Shelfrip is already running on that port."""
    for port in range(review.PORT, review.PORT + 20):
        if _is_shelfrip(port):
            return None, port
        if _port_taken(port):
            print(f"Port {port} is used by another program; trying {port + 1}.")
            continue
        try:
            return Server(("127.0.0.1", port), Handler), port
        except OSError:
            continue
    raise SystemExit(f"Couldn't find a free port between {review.PORT} and {review.PORT + 19}.")


def main() -> None:
    global RIPPER
    if desktop.use_log_file():
        print(f"\n=== Shelfrip {paths.APP_VERSION} started {time.strftime('%Y-%m-%d %H:%M:%S')}")
    srv, port = open_server()
    review.PORT = port
    url = f"http://127.0.0.1:{port}/"
    cfg = _read_config()
    use_window = cfg.get("app_window", True)
    if srv is None:
        print("Shelfrip is already running. Opening it.")
        desktop.open_window(url, use_window)
        return
    if paths.MIGRATION_NOTE:
        print(paths.MIGRATION_NOTE)
    RIPPER = Ripper()
    threading.Thread(target=check_update, daemon=True).start()
    try:
        if review.RIP_ROOT.exists():
            print("Naming new rips...")
            print(f"  {review.plan_new_folders()} new disc(s) named.")
    except Exception as exc:
        print(f"  couldn't name new rips: {exc}")
    print(f"Shelfrip: {url}  (quit from the tray icon by the clock, or the Quit button on the page)")
    if cfg.get("tray_icon", True) or sys.stdout is None or not desktop.owns_console():
        start_tray(url, use_window)  # with no console window, the tray icon is the way to quit
    if "--background" not in sys.argv:  # started with Windows: don't pop the page open
        threading.Timer(0.8, lambda: desktop.open_window(url, use_window)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
