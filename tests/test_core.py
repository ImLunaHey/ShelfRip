"""
test_core.py - filing, recovery and re-matching, on made-up discs (no internet needed).

Run on its own (python tests/test_core.py): Shelfrip reads its settings when first imported,
so each test file gets its own process.
"""

from __future__ import annotations

import json
import shutil
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

TMP = discs.setup_env({"tmdb_api_key": "", "eject_after_filing": False, "format_folders": True,
                       "media_server": "plex"})
(TMP / "lib").mkdir()
import review  # noqa: E402


def make_disc(name: str, items: list[dict], title="Test", year="2000", tmdb="1", filing=None) -> Path:
    d = TMP / "rip" / name
    d.mkdir()
    (d / "disc_info.json").write_text("{}")
    for it in items:
        (d / it["source"]).write_bytes(b"x" * 1000)
    plan = {"kind": "movie", "title": title, "year": year, "tmdb_id": tmdb, "status": "proposed", "format": "DVD",
            "disc_label": name.split("__")[0], "library_dir": f"Movies\\{title} ({year}) {{tmdb-{tmdb}}}", "items": items}
    if filing:
        plan["filing"] = filing
    review.save_plan(d, plan)
    return d


def movie_items(title="Test", year="2000", tmdb="1"):
    base = f"{title} ({year}) {{tmdb-{tmdb}}}"
    folder = f"Movies\\{base}"
    return [{"source": "a.mkv", "action": "move", "role": "main", "dest_dir": folder, "name": base},
            {"source": "b.mkv", "action": "move", "role": "extra", "category": "Featurettes", "dest_dir": folder,
             "name": "Making Of"}]


def wait_job(name):
    for _ in range(100):
        if review.JOBS.get(name, {}).get("state") in ("done", "error"):
            return review.JOBS[name]
        time.sleep(0.05)
    return review.JOBS.get(name)


class Core(unittest.TestCase):
    def setUp(self):
        review.JOBS.clear()

    def test_save_plan_is_whole_and_drops_runtime_keys(self):
        d = make_disc("SAVE__1", movie_items())
        plan = json.loads((d / "plan.json").read_text())
        plan.update(job={"x": 1}, folder="z", auto={"at": 1})
        review.save_plan(d, plan)
        saved = json.loads((d / "plan.json").read_text())
        self.assertFalse({"job", "folder", "auto"} & set(saved))
        self.assertFalse((d / "plan.json.tmp").exists())

    def test_library_away_stops_filing(self):
        d = make_disc("AWAY__1", movie_items("Away", tmdb="2"))
        real = review.LIB_ROOT
        review.LIB_ROOT = TMP / "nowhere"
        try:
            problems = review.check_plan(d, json.loads((d / "plan.json").read_text()))
        finally:
            review.LIB_ROOT = real
        self.assertTrue(problems and problems[0].startswith("Your library"))

    def test_interrupted_filing_is_finished(self):
        items = movie_items("Resume", tmdb="3")
        d = make_disc("RESUME__1", items, "Resume", tmdb="3", filing={"started": "x", "tries": 1, "at": time.time()})
        plan = json.loads((d / "plan.json").read_text())
        first = review.dest_for(plan["items"][0], plan)  # copied before the interruption
        first.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d / "a.mkv"), first)
        plan["items"][0]["filed_to"] = str(first)
        review.save_plan(d, plan)
        self.assertEqual(review.resume_tick(log=lambda *a: None), ["Resume"])
        self.assertEqual(wait_job("RESUME__1")["state"], "done")
        self.assertTrue(first.exists())
        self.assertTrue(review.dest_for(plan["items"][1], plan).exists())
        rec = json.loads((TMP / "rip" / "_Filed" / "RESUME__1" / "plan.json").read_text())
        self.assertEqual(rec["status"], "filed")
        self.assertNotIn("filing", rec)

    def test_moved_but_not_noted_counts_as_done(self):
        d = make_disc("NOTED__1", movie_items("Noted", tmdb="4")[:1], "Noted", tmdb="4",
                      filing={"started": "x", "tries": 1, "at": time.time()})
        plan = json.loads((d / "plan.json").read_text())
        dst = review.dest_for(plan["items"][0], plan)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(d / "a.mkv"), dst)
        self.assertEqual(review.check_plan(d, plan), [])

    def test_bad_copy_keeps_the_original(self):
        real_tool, real_len = review.split.tool, review._length
        review.split.tool = lambda cfg, n: "mkvmerge"
        review._length = lambda p, m: 100.0 if p.name == "a.mkv" else 90.0
        try:
            self.assertIn("90 s instead of 100 s", review.verify_copy(Path("a.mkv"), Path("b.mkv")))
            review._length = lambda p, m: 100.0
            self.assertEqual(review.verify_copy(Path("a.mkv"), Path("b.mkv")), "")
        finally:
            review.split.tool, review._length = real_tool, real_len

    def test_refile_wrong_movie(self):
        name = "WRONG__20261117-191550"
        d = make_disc(name, movie_items("Wrong", "1999", "5"), "Wrong", "1999", "5")
        plan = json.loads((d / "plan.json").read_text())
        self.assertEqual(review.start_filing(d, plan), [])
        self.assertEqual(wait_job(name)["state"], "done")

        class FakeTMDB:
            def movie(self, mid):
                return {"title": "Right Movie", "release_date": "2001-08-17"}
        real = review.TMDB
        review.TMDB = FakeTMDB()
        try:
            r = review.refile_movie(name, "6", log=lambda *a: None)
            again = review.refile_movie(name, "6", log=lambda *a: None)
            bad = review.refile_movie("../x", "6", log=lambda *a: None)
        finally:
            review.TMDB = real
        self.assertTrue(r.get("ok"), r)
        new = TMP / "lib" / "Movies" / "Right Movie (2001) {tmdb-6}"
        self.assertTrue((new / "Right Movie (2001) {tmdb-6}.mkv").exists())
        self.assertTrue((new / "Featurettes" / "Making Of.mkv").exists())
        self.assertFalse((TMP / "lib" / "Movies" / "Wrong (1999) {tmdb-5}").exists())
        rec = json.loads((TMP / "rip" / "_Filed" / name / "plan.json").read_text())
        self.assertEqual((rec["title"], rec["year"], rec["tmdb_id"]), ("Right Movie", "2001", "6"))
        self.assertIn("error", again)
        self.assertIn("error", bad)


if __name__ == "__main__":
    unittest.main()
