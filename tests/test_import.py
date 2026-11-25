"""
test_import.py - importing a folder of videos ripped before: what's refused, the label taken
from the folder's name, disc_info.json built from MKVToolNix, and the folder named for review.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

TMP = discs.setup_env({"tmdb_api_key": "", "eject_after_filing": False, "use_community": False, "use_thediscdb": False})
(TMP / "lib" / "Movies").mkdir(parents=True)
import importer  # noqa: E402
import review  # noqa: E402

# a stand-in for mkvmerge -J: a 2-hour 1080p film and a 10-minute extra, by file size
TOOLS = TMP / "tools"
TOOLS.mkdir()
fake = TOOLS / "mkvmerge"
fake.write_text(f"#!{sys.executable}\n" + textwrap.dedent('''
    import json, os, sys
    big = os.path.getsize(sys.argv[-1]) > 500
    print(json.dumps({
        "container": {"properties": {"duration": (7200 if big else 600) * 10**9, "title": "Main" if big else ""}},
        "chapters": [{"num_entries": 16 if big else 1}],
        "tracks": [
            {"type": "video", "codec": "AVC", "properties": {"codec_id": "V_MPEG4/ISO/AVC", "pixel_dimensions": "1920x1080"}},
            {"type": "audio", "codec": "DTS-HD MA", "properties": {"codec_id": "A_DTS", "language": "eng", "audio_channels": 6}},
            {"type": "audio", "codec": "AC-3", "properties": {"codec_id": "A_AC3", "language": "eng", "audio_channels": 2,
                                                             "track_name": "Director's Commentary"}},
            {"type": "subtitles", "codec": "PGS", "properties": {"codec_id": "S_HDMV/PGS", "language": "eng"}}]}))
'''))
fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
CFG = {"mkvtoolnix_dir": str(TOOLS)}


def folder(name: str, files: dict[str, int]) -> Path:
    d = TMP / "old" / name
    d.mkdir(parents=True)
    for f, size in files.items():
        (d / f).write_bytes(b"x" * size)
    return d


class Labels(unittest.TestCase):
    def test_labels(self):
        for name, want in [("Inception (2010) {tmdb-27205} [1080p]", "Inception"),
                           ("Inception.2010.1080p.BluRay", "Inception"),
                           ("Blade Runner 2049 (2017)", "Blade Runner 2049"),
                           ("Blade.Runner.2049.2017.2160p", "Blade.Runner.2049"),
                           ("THE_SANTA_CLAUSE_2", "THE_SANTA_CLAUSE_2"),
                           ("1917", "1917")]:
            self.assertEqual(importer.label_for(name), want)


class Refused(unittest.TestCase):
    def test_problems(self):
        libs = [TMP / "lib" / "Movies"]
        self.assertIn("doesn't exist", importer.problem(TMP / "nope", review.RIP_ROOT, libs))
        self.assertIn("no MKV", importer.problem(folder("EMPTY", {"a.txt": 3}), review.RIP_ROOT, libs))
        inside = review.RIP_ROOT / "X__1"
        inside.mkdir()
        (inside / "a.mkv").write_bytes(b"x")
        self.assertIn("already in the rip folder", importer.problem(inside, review.RIP_ROOT, libs))
        (TMP / "lib" / "Movies" / "Film").mkdir()
        (TMP / "lib" / "Movies" / "Film" / "a.mkv").write_bytes(b"x")
        self.assertIn("media library", importer.problem(TMP / "lib" / "Movies" / "Film", review.RIP_ROOT, libs))
        self.assertIn("media library", importer.problem(TMP / "lib", review.RIP_ROOT, libs))
        self.assertIn("holds the rip folder", importer.problem(TMP, review.RIP_ROOT, libs))
        self.assertEqual(importer.problem(folder("FINE", {"t.mkv": 9}), review.RIP_ROOT, libs), "")


@unittest.skipIf(os.name == "nt", "uses a shebang script as a stand-in for mkvmerge")
class Import(unittest.TestCase):
    def test_describe(self):
        src = folder("MOVIE_DESCRIBE", {"title_t00.mkv": 1000, "title_t03.mkv": 100})
        info = importer.describe(src, str(fake))
        self.assertEqual(info["disc_label"], "MOVIE_DESCRIBE")
        t0, t3 = info["titles"]
        self.assertEqual((t0["title_id"], t3["title_id"]), (0, 3))
        self.assertEqual((t0["duration_seconds"], t0["duration"], t0["chapters"]), (7200, "2:00:00", 16))
        v, a1, a2, s = t0["streams"]
        self.assertEqual((v["type"], v["resolution"], v["codec"]), ("Video", "1920x1080", "H264"))
        self.assertEqual((a1["codec"], a1["channels"], a1["lang3"]), ("DTS", 6, "eng"))
        self.assertEqual((a2.get("flags"), a2["name"]), (1, "Director's Commentary"))
        self.assertEqual(s["type"], "Subtitles")

    def test_run_moves_and_names(self):
        src = folder("Some Film (1999)", {"title_t00.mkv": 1000, "title_t01.mkv": 100})
        dest = importer.run(src, review.RIP_ROOT, CFG, log=lambda *_: None, on_done=lambda _d: review.plan_new_folders())
        self.assertTrue(dest.name.startswith("Some Film__import-"))
        self.assertEqual(sorted(p.name for p in dest.glob("*.mkv")), ["title_t00.mkv", "title_t01.mkv"])
        self.assertEqual(importer.videos(src), [])  # same drive: moved, not copied
        info = json.loads((dest / "disc_info.json").read_text())
        self.assertEqual((info["disc_label"], info["imported_from"]), ("Some Film", str(src)))
        plan = json.loads((dest / "plan.json").read_text())
        self.assertEqual(plan["kind"], "movie")
        main = [it for it in plan["items"] if it["role"] == "main"]
        self.assertEqual([it["source"] for it in main], ["title_t00.mkv"])
        self.assertEqual(importer.JOBS.get(str(src), {}).get("state"), "named")

    def test_other_drive_copies(self):
        src = folder("COPY_ME", {"a_t00.mkv": 1000})
        old = importer.same_drive
        importer.same_drive = lambda a, b: False
        try:
            dest = importer.run(src, review.RIP_ROOT, CFG, log=lambda *_: None)
        finally:
            importer.same_drive = old
        self.assertTrue((dest / "a_t00.mkv").exists() and (src / "a_t00.mkv").exists())


if __name__ == "__main__":
    unittest.main()
