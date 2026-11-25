"""
test_ripping.py - how a rip is run: MakeMKV's progress, one pass or one title at a time,
what a failed rip says, and folder errors that name the folder.
"""

from __future__ import annotations

import os
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

import paths  # noqa: E402
import rip_all  # noqa: E402

# what makemkvcon -r --progress=-same prints for one `mkv` run: it opens and analyses the disc
# (with its own progress bar), then saves
FAKE_RUN = [
    'PRGT:5018,0,"Scanning CD-ROM devices"', 'PRGV:0,0,65536', 'PRGV:0,65536,65536',
    'PRGT:3404,0,"Opening Blu-ray disc"', 'PRGC:5057,0,"Analyzing seamless segments"',
    'PRGV:0,54000,65536',  # 83% through the analysis: not ripping progress
    'PRGT:5024,0,"Saving all titles to MKV files"', 'PRGC:5017,0,"Saving to MKV file"',
    'PRGV:0,0,65536', 'PRGV:0,32768,65536', 'PRGV:0,65536,65536',
    'MSG:5005,128,1,"1 titles saved","%1 titles saved","1"',
]


def fake_makemkvcon(lines: list[str]) -> str:
    d = Path(tempfile.mkdtemp())
    f = d / "makemkvcon"
    f.write_text(f"#!{sys.executable}\n" + textwrap.dedent(f"""
        for line in {lines!r}:
            print(line, flush=True)
    """))
    f.chmod(f.stat().st_mode | stat.S_IEXEC)
    return str(f)


@unittest.skipIf(os.name == "nt", "uses a shebang script as a stand-in for makemkvcon")
class Progress(unittest.TestCase):
    def test_only_saving_counts(self):
        seen, phases = [], []
        rc, out = rip_all.run_makemkv({"makemkvcon_path": fake_makemkvcon(FAKE_RUN)}, ["mkv", "disc:0", "0", "/tmp"],
                                      on_progress=seen.append, on_phase=phases.append)
        self.assertEqual(rc, 0)
        self.assertEqual(seen, [0.0, 0.5, 1.0])  # the 83% from the disc analysis is left out
        self.assertIn("Analyzing seamless segments", phases)
        self.assertEqual(phases[-1], "")  # saving: no phase shown
        self.assertIn("1 titles saved", out)

    def test_no_phase_lines_still_reports(self):
        seen = []
        rip_all.run_makemkv({"makemkvcon_path": fake_makemkvcon(["PRGV:0,10,20"])}, ["info"], on_progress=seen.append)
        self.assertEqual(seen, [0.5])


def title(tid: int, size: float, skip: bool = False) -> dict:
    t = {"title_id": tid, "size_bytes": int(size), "output_file": f"t{tid:02}.mkv", "duration_seconds": 60}
    if skip:
        t["skipped_duplicate_of"] = 0
    return t


class OnePass(unittest.TestCase):
    def setUp(self):
        self.out = Path(tempfile.mkdtemp())

    def test_many_extras_small_skips_rips_everything_once(self):
        # like Ghostbusters (2016): 27 titles to rip, a 3-minute disc analysis before each
        todo = [title(i, 3e8) for i in range(27)]
        skipped = [title(100 + i, 2e8, True) for i in range(80)]  # 16 GB of scene titles
        if rip_all.shutil.disk_usage(self.out).free < 30e9:
            self.skipTest("needs 30 GB free for the extra copies")
        self.assertTrue(rip_all.rip_all_cheaper({"min_free_gb_rips": 0}, {"disc_layout": "bluray"}, todo,
                                                todo + skipped, 190, self.out))

    def test_big_duplicate_feature_rips_one_by_one(self):
        todo = [title(0, 30e9)] + [title(i, 3e8) for i in range(1, 5)]
        skipped = [title(9, 30e9, True)]  # a second 30 GB copy of the movie
        self.assertFalse(rip_all.rip_all_cheaper({"min_free_gb_rips": 0}, {"disc_layout": "bluray"}, todo,
                                                 todo + skipped, 190, self.out))

    def test_one_title_never(self):
        self.assertFalse(rip_all.rip_all_cheaper({}, {}, [title(0, 1e9)], [title(0, 1e9), title(1, 1, True)], 600, self.out))

    def test_not_enough_room(self):
        todo = [title(i, 3e8) for i in range(27)]
        skipped = [title(100, 1e15, True)]  # more than any disk has free
        self.assertFalse(rip_all.rip_all_cheaper({}, {}, todo, todo + skipped, 190, self.out))


class Finished(unittest.TestCase):
    def test_size_fallback_allows_estimate_slack(self):
        f = Path(tempfile.mkdtemp()) / "t00.mkv"
        f.write_bytes(b"x" * 920)
        cfg = {"mkvtoolnix_dir": "/nonexistent"}
        self.assertTrue(rip_all.title_complete(cfg, f, {"size_bytes": 1000}))
        self.assertFalse(rip_all.title_complete(cfg, f, {"size_bytes": 2000}))


class Messages(unittest.TestCase):
    def test_makemkv_problem(self):
        out = "\n".join([
            'MSG:4004,0,2,"The source file \'/VIDEO_TS/VTS_01_1.VOB\' is corrupt or invalid at offset 4096, attempting to work around","x"',
            'MSG:5003,0,2,"Failed to save title 3 to file E:/Ripped/X/t03.mkv","Failed to save title %1 to file %2"',
            'MSG:5004,0,2,"2 titles saved, 1 failed","%1 titles saved, %2 failed"',
        ])
        self.assertEqual(rip_all.makemkv_problem(out), "Failed to save title 3 to file E:/Ripped/X/t03.mkv")
        self.assertEqual(rip_all.makemkv_problem('MSG:5005,128,1,"1 titles saved","%1 titles saved","1"'), "")

    def test_title_summary(self):
        disc = rip_all.parse_disc_info("\n".join([
            'TINFO:0,9,0,"1:56:58"', 'TINFO:0,11,0,"30000000000"', 'TINFO:0,8,0,"28"', 'TINFO:0,16,0,"00800.mpls"',
            'SINFO:0,0,1,6201,"Video"', 'SINFO:0,0,6,0,"MPEG4-AVC"', 'SINFO:0,0,19,0,"1920x1080"',
            'SINFO:0,1,1,6202,"Audio"', 'SINFO:0,1,4,0,"English"', 'SINFO:0,1,6,0,"DTS-HD MA"',
            'SINFO:0,2,1,6203,"Subtitles"', 'SINFO:0,2,4,0,"French"',
        ]))
        s = rip_all.title_summary(disc)[0]
        self.assertEqual((s["length"], s["size"], s["chapters"], s["source"]), ("1:56:58", 30000000000, 28, "00800.mpls"))
        self.assertEqual(s["video"], "MPEG4-AVC 1920x1080")
        self.assertEqual(s["audio"], ["English DTS-HD MA"])
        self.assertEqual(s["subtitles"], ["French"])

    def test_folder_errors_name_the_folder(self):
        msg = paths.folder_problem(Path("D:/Videos/Ripped"), PermissionError(13, "Access is denied"), "the rip folder")
        self.assertIn("D:", msg)
        self.assertIn("Controlled folder access", msg)
        msg = paths.folder_problem(Path("Q:/Rips"), FileNotFoundError(2, "nope"), "the rip folder")
        self.assertIn("doesn't exist", msg)

    def test_make_folder_raises_readable_error(self):
        f = Path(tempfile.mkdtemp()) / "a file"
        f.write_text("")
        with self.assertRaises(OSError) as cm:
            paths.make_folder(f / "inside", "the rip folder")
        self.assertIn("Couldn't create the rip folder", str(cm.exception))
        self.assertIn(str(f / "inside"), str(cm.exception))


if __name__ == "__main__":
    unittest.main()
