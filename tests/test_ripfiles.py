"""
test_ripfiles.py - titles that MakeMKV's file name template gives one shared name (a tester's
Mortal Kombat II rip, 2026-11-25) are matched to the files really written.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

import ripfiles  # noqa: E402

NAME = "Mortal Kombat II.mkv"


def disc(*lengths: int) -> dict:
    return {"titles": [{"title_id": i, "output_file": NAME, "duration_seconds": d, "size_bytes": d * 1000}
                       for i, d in enumerate(lengths)]}


def folder(files: dict[str, int]) -> Path:
    d = Path(tempfile.mkdtemp())
    for name, n in files.items():
        (d / name).write_bytes(b"x" * n)
    return d


class Unclash(unittest.TestCase):
    def test_shared_names_get_their_own(self):
        dc = disc(7000, 600, 300)
        self.assertEqual(ripfiles.unclash(dc), 3)
        self.assertEqual([t["output_file"] for t in dc["titles"]],
                         ["Mortal Kombat II_t00.mkv", "Mortal Kombat II_t01.mkv", "Mortal Kombat II_t02.mkv"])
        self.assertTrue(all(t["makemkv_name"] == NAME for t in dc["titles"]))

    def test_normal_names_left_alone(self):
        dc = {"titles": [{"title_id": 0, "output_file": "A_t00.mkv"}, {"title_id": 1, "output_file": "A_t01.mkv"}]}
        self.assertEqual(ripfiles.unclash(dc), 0)
        self.assertNotIn("name_clash", dc)


class Match(unittest.TestCase):
    def test_by_title_suffix(self):
        dc = disc(7000, 600, 300)
        d = folder({NAME: 7, "Mortal Kombat II_t01.mkv": 6, "Mortal Kombat II_t02.mkv": 3})
        lens = {NAME: 7000, "Mortal Kombat II_t01.mkv": 600, "Mortal Kombat II_t02.mkv": 300}
        self.assertTrue(ripfiles.match_files(d, dc, length=lambda p: lens[p.name]))
        self.assertEqual([t["output_file"] for t in dc["titles"]], [NAME, "Mortal Kombat II_t01.mkv",
                                                                     "Mortal Kombat II_t02.mkv"])

    def test_by_length_when_names_say_nothing(self):
        dc = disc(7000, 600, 300)
        lens = {"a.mkv": 300, "b.mkv": 7000, "c.mkv": 602}
        d = folder({n: 1 for n in lens})
        ripfiles.match_files(d, dc, length=lambda p: lens[p.name])
        self.assertEqual([t["output_file"] for t in dc["titles"]], ["b.mkv", "c.mkv", "a.mkv"])

    def test_a_missing_file_leaves_the_title_unripped(self):
        dc = disc(7000, 600)
        lens = {"b.mkv": 7000}
        d = folder({"b.mkv": 1})
        ripfiles.match_files(d, dc, length=lambda p: lens[p.name])
        self.assertEqual(dc["titles"][0]["output_file"], "b.mkv")
        self.assertEqual(dc["titles"][1]["output_file"], "Mortal Kombat II_t01.mkv")
        self.assertFalse((d / dc["titles"][1]["output_file"]).exists())

    def test_wrong_length_suffix_not_trusted(self):
        dc = disc(7000, 600)
        lens = {"Mortal Kombat II_t00.mkv": 600, "Mortal Kombat II_t01.mkv": 7000}  # _t means something else
        d = folder({n: 1 for n in lens})
        ripfiles.match_files(d, dc, length=lambda p: lens[p.name])
        self.assertEqual([t["output_file"] for t in dc["titles"]], ["Mortal Kombat II_t01.mkv",
                                                                     "Mortal Kombat II_t00.mkv"])

    def test_by_size_without_mkvtoolnix(self):
        dc = disc(7000, 600)
        d = folder({"x.mkv": 600_000, "y.mkv": 7_000_000})
        ripfiles.match_files(d, dc, length=lambda p: 0)
        self.assertEqual([t["output_file"] for t in dc["titles"]], ["y.mkv", "x.mkv"])

    def test_a_normal_rip_is_untouched(self):
        dc = {"titles": [{"title_id": 0, "output_file": "A_t00.mkv", "duration_seconds": 7000},
                         {"title_id": 1, "output_file": "A_t01.mkv", "duration_seconds": 60}]}  # left out, deleted
        d = folder({"A_t00.mkv": 1})
        self.assertFalse(ripfiles.match_files(d, dc, length=lambda p: 7000))
        self.assertEqual(dc["titles"][1]["output_file"], "A_t01.mkv")

    def test_repair_rewrites_disc_info(self):
        dc = disc(7000, 7000)  # two copies of the film: sizes tell them apart
        dc["titles"][1]["size_bytes"] = 7_100_000
        dc["titles"][0]["size_bytes"] = 7_000_000
        d = folder({"Mortal Kombat II_t00.mkv": 7_000_000, "Mortal Kombat II_t01.mkv": 7_100_000})
        (d / "disc_info.json").write_text(json.dumps(dc))
        self.assertTrue(ripfiles.repair(d))
        got = json.loads((d / "disc_info.json").read_text())
        self.assertEqual([t["output_file"] for t in got["titles"]], ["Mortal Kombat II_t00.mkv",
                                                                     "Mortal Kombat II_t01.mkv"])
        self.assertFalse(ripfiles.repair(d))  # nothing left to fix


class OneTitle(unittest.TestCase):
    def test_new_file_takes_the_titles_name(self):
        import rip_all
        dc = disc(7000, 600)
        ripfiles.unclash(dc)
        d = folder({"Mortal Kombat II_t00.mkv": 5})
        import time
        since = time.time() + 1
        (d / NAME).write_bytes(b"y")  # MakeMKV's own name for title 1
        os.utime(d / NAME, (since + 1, since + 1))
        rip_all.claim_new_file(d, dc["titles"][1], since, dc)
        self.assertTrue((d / "Mortal Kombat II_t01.mkv").exists())
        self.assertFalse((d / NAME).exists())
        self.assertTrue((d / "Mortal Kombat II_t00.mkv").exists())


if __name__ == "__main__":
    unittest.main()
