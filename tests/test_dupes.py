"""
test_dupes.py - leaving out extra copies of the main feature before ripping (dupes.py), with no
internet and no MakeMKV: the disc scan and the rip are faked.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

TMP = discs.setup_env({"tmdb_api_key": "", "use_community": False, "use_thediscdb": False})
import dupes  # noqa: E402
import rip_all  # noqa: E402

ENG51 = {"type": "Audio", "lang3": "eng", "codec": "DTS-HD MA", "channels": 6}
FRA51 = {"type": "Audio", "lang3": "fra", "codec": "DTS", "channels": 6}
COMM = {"type": "Audio", "lang3": "eng", "codec": "AC3", "channels": 2, "name": "Commentary"}
SUB = {"type": "Subtitles", "lang3": "eng", "codec": "PGS"}
VIDEO = {"type": "Video", "codec": "MPEG4-AVC", "resolution": "1920x1080"}


def title(tid, secs, segs="", size=30_000_000_000, streams=None, chapters=24, src=""):
    return {"title_id": tid, "duration_seconds": secs, "segments": segs, "size_bytes": size, "chapters": chapters,
            "source_file": src or f"{800 + tid:05d}.mpls", "output_file": f"title_t{tid:02d}.mkv",
            "streams": [VIDEO] + (streams if streams is not None else [ENG51, SUB])}


def main_row(size, src=""):
    return {"itemType": "MainMovie", "size": size, "sourceFile": src}


class SameContent(unittest.TestCase):
    def test_identical_copies_keep_one(self):
        ts = [title(0, 7200, "1,2,3"), title(1, 7200, "1,2,3"), title(2, 300, "9")]
        self.assertEqual(dupes.find(ts), {1: (0, "same clips and tracks")})

    def test_keeps_the_copy_with_more_tracks(self):
        ts = [title(0, 7200, "1,2,3"), title(1, 7200, "1,2,3", streams=[ENG51, COMM, SUB])]
        self.assertEqual(set(dupes.find(ts)), {0})

    def test_different_tracks_are_both_kept(self):
        # same picture, but each has a soundtrack the other lacks: never drop a track
        ts = [title(0, 7200, "1,2,3", streams=[ENG51]), title(1, 7200, "1,2,3", streams=[FRA51])]
        self.assertEqual(dupes.find(ts), {})

    def test_language_version_with_other_clips_is_kept(self):
        ts = [title(0, 7200, "1,2,3,4"), title(1, 7201, "1,2,3,5")]
        self.assertEqual(dupes.find(ts), {})

    def test_different_cuts_are_kept(self):
        ts = [title(0, 7200, "1,2,3"), title(1, 8100, "1,2,3,4")]
        self.assertEqual(dupes.find(ts), {})

    def test_short_titles_are_left_alone(self):
        ts = [title(0, 1300, "1"), title(1, 1300, "1")]
        self.assertEqual(dupes.find(ts), {})


class Decoys(unittest.TestCase):
    def decoys(self, sizes):
        return [title(i, 7380 + i % 2, ",".join(str((i + k) % 40) for k in range(40)), size=s)
                for i, s in enumerate(sizes)]

    def test_database_pick_drops_unknown_decoys(self):
        ts = self.decoys([30_000_000_000, 30_000_000_123, 30_000_000_456])
        known = {"kind": "movie", "pairs": {ts[1]["output_file"]: main_row(30_000_000_123)}}
        self.assertEqual(set(dupes.find(ts, known)), {0, 2})

    def test_ambiguous_database_pick_keeps_everything(self):
        ts = self.decoys([30_000_000_000] * 3)  # same size: the database's pick could be any of them
        known = {"kind": "movie", "pairs": {ts[0]["output_file"]: main_row(30_000_000_000)}}
        self.assertEqual(dupes.find(ts, known), {})

    def test_playlist_name_settles_same_size(self):
        ts = self.decoys([30_000_000_000] * 3)
        known = {"kind": "movie", "pairs": {ts[2]["output_file"]: main_row(30_000_000_000, ts[2]["source_file"])}}
        self.assertEqual(set(dupes.find(ts, known)), {0, 1})

    def test_two_known_features_are_both_kept(self):
        ts = self.decoys([30_000_000_000, 30_000_000_123])
        known = {"kind": "movie", "pairs": {t["output_file"]: main_row(t["size_bytes"]) for t in ts}}
        self.assertEqual(dupes.find(ts, known), {})

    def test_no_database_keeps_everything(self):
        self.assertEqual(dupes.find(self.decoys([30_000_000_000, 30_000_000_123])), {})


class RipDisc(unittest.TestCase):
    """rip_disc rips only the titles that are left, one by one, and records what it left out."""

    def run_rip(self, setting):
        disc = {"titles": [title(0, 7200, "1,2,3"), title(1, 7200, "1,2,3"), title(2, 600, "7")]}
        calls = []

        def fake(cfg, args, logfile=None, on_progress=None, device=""):
            calls.append(args)
            if args[1] == "info":
                return 0, "info"
            out = Path(args[-1])
            ids = [t["title_id"] for t in disc["titles"]] if args[3] == "all" else [int(args[3])]
            for t in disc["titles"]:
                if t["title_id"] in ids:
                    (out / t["output_file"]).write_bytes(b"x")
            return 0, ""

        cfg = {**rip_all.DEFAULT_CONFIG, "output_root": str(TMP / "rip"), "skip_duplicate_features": setting, "eject_when_done": False,
               "retry_failed_titles": False, "use_community": False, "use_thediscdb": False}
        rip_all.run_makemkv, old_run = fake, rip_all.run_makemkv
        rip_all.parse_disc_info, old_parse = (lambda _: json.loads(json.dumps(disc))), rip_all.parse_disc_info
        try:
            info = rip_all.rip_disc(cfg, {"device": "disc:9", "disc_label": f"DUPES_{setting}", "drive_name": "x", "index": 9})
        finally:
            rip_all.run_makemkv, rip_all.parse_disc_info = old_run, old_parse
        return info, [c for c in calls if c[1] == "mkv"]

    def test_setting_on(self):
        info, rips = self.run_rip(True)
        self.assertEqual([c[3] for c in rips], ["0", "2"])
        self.assertEqual(info["status"], "ok")
        self.assertEqual(info["skipped_duplicates"], 1)
        t1 = info["titles"][1]
        self.assertEqual((t1["skipped_duplicate_of"], t1["ripped"]), (0, False))

    def test_setting_off(self):
        info, rips = self.run_rip(False)
        self.assertEqual([c[3] for c in rips], ["all"])
        self.assertNotIn("skipped_duplicates", info)


if __name__ == "__main__":
    unittest.main()
