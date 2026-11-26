"""
test_libraries.py - "Use multiple libraries": other library folders (a separate 4K library, say),
the default library for each disc format, moving a disc to another library before filing, and
where its files then go.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

TMP = discs.setup_env({"tmdb_api_key": ""})
import identify  # noqa: E402
import review  # noqa: E402


def lib(*folders: str) -> Path:
    root = Path(tempfile.mkdtemp(dir=TMP))
    for f in folders:
        (root / f).mkdir(parents=True)
    return root


def config(main: Path, *others: dict, on: bool = True, **extra) -> dict:
    return {**identify.DEFAULTS, "plex_library_root": str(main), "multiple_libraries": on,
            "libraries": list(others), **extra}


def movie_plan(cfg: dict, fmt_dir: str = "") -> dict:
    top = identify.library_dirs(cfg)["movies"]
    d = "\\".join(x for x in (top, fmt_dir, "Some Film (2001)") if x)
    return {"kind": "movie", "title": "Some Film", "year": "2001", "format": "4K Blu-Ray", "library_dir": d,
            "items": [{"source": "a.mkv", "role": "main", "action": "move", "name": "Some Film (2001)", "dest_dir": d},
                      {"source": "b.mkv", "role": "extra", "action": "move", "category": "Featurettes",
                       "name": "Making Of", "dest_dir": d}]}


class Settings(unittest.TestCase):
    def test_off_means_one_library(self):
        main, k4 = lib(), lib()
        cfg = config(main, {"name": "4K", "path": str(k4), "formats": ["4k"]}, on=False)
        self.assertEqual(identify.extra_libraries(cfg), [])
        self.assertEqual(len(identify.library_choices(cfg)), 1)
        self.assertEqual(identify.default_library(cfg, "4k"), "")

    def test_tidied_and_defaults_by_format(self):
        main, k4 = lib(), lib()
        cfg = config(main, {"name": "", "path": str(k4) + "/", "formats": ["4k", "vhs"]},
                     {"name": "Same as main", "path": str(main), "formats": ["dvd"]},
                     {"name": "Not chosen yet", "path": "  ", "formats": ["bluray"]},
                     {"name": "Again", "path": str(k4), "formats": []})
        extra = identify.extra_libraries(cfg)
        self.assertEqual(extra, [{"name": k4.name, "path": str(k4), "formats": ["4k"]}])
        self.assertEqual(identify.default_library(cfg, "4k"), str(k4))
        self.assertEqual(identify.default_library(cfg, "bluray"), "")
        self.assertEqual([x["name"] for x in identify.library_choices(cfg)], ["Main library", k4.name])
        self.assertEqual(identify.known_library(cfg, str(k4).upper() if sys.platform == "win32" else str(k4)), str(k4))
        self.assertEqual(identify.known_library(cfg, str(TMP / "gone")), "")

    def test_library_cfg_keeps_folder_names_not_full_paths(self):
        main, k4 = lib("Films"), lib("films")
        cfg = config(main, {"name": "4K", "path": str(k4)}, movies_folder="Films", tv_folder=str(TMP / "tv-elsewhere"))
        other = identify.library_cfg(cfg, str(k4))
        self.assertEqual(other["plex_library_root"], str(k4))
        self.assertEqual(identify.library_dirs(other, k4), {"movies": "films", "tv": "TV Shows"})
        self.assertIs(identify.library_cfg(cfg, str(main)), cfg)
        self.assertIs(identify.library_cfg(cfg, ""), cfg)

    def test_settings_page_checks_the_list(self):
        import app
        main, k4 = lib(), lib()
        got = app._clean_libraries([{"name": " 4K ", "path": str(k4), "formats": ["4k", "x"]}, {"path": ""}, "junk"], str(main))
        self.assertEqual(got, [{"name": "4K", "path": str(k4), "formats": ["4k"]}, {"name": "", "path": "", "formats": []}])
        with self.assertRaises(ValueError):
            app._clean_libraries([{"path": str(main)}], str(main))
        with self.assertRaises(ValueError):
            app._clean_libraries([{"path": "just a name"}], str(main))

    def test_rip_folder_inside_another_library_is_flagged(self):
        import app
        main, k4 = lib(), lib()
        cfg = config(main, {"name": "4K", "path": str(k4)})
        self.assertEqual(app.rip_folder_in_library(str(k4 / "Ripped"), cfg), str(k4))
        self.assertEqual(app.rip_folder_in_library(str(k4 / "Ripped"), {**cfg, "multiple_libraries": False}), "")


class Retarget(unittest.TestCase):
    def test_movie_moves_to_the_other_library_and_back(self):
        main, k4 = lib("Movies"), lib("movies")
        cfg = config(main, {"name": "4K", "path": str(k4)}, format_folders=True)
        plan = movie_plan(cfg, "4K Blu-Ray")
        plan["warnings"] = ["Extras will go into the movie's existing folder (Movies\\Some Film (2001))."]
        self.assertEqual(identify.retarget_library(plan, cfg, str(k4)), "")
        self.assertEqual(plan["library_root"], str(k4))
        self.assertEqual(plan["library_dir"], "movies\\4K Blu-Ray\\Some Film (2001)")  # its own folder's case
        self.assertTrue(all(it["dest_dir"] == plan["library_dir"] for it in plan["items"]))
        self.assertEqual(plan["warnings"], [])
        self.assertEqual(identify.retarget_library(plan, cfg, ""), "")
        self.assertNotIn("library_root", plan)
        self.assertEqual(plan["library_dir"], "Movies\\4K Blu-Ray\\Some Film (2001)")

    def test_tv_keeps_season_folders(self):
        main, k4 = lib("Series"), lib()
        cfg = config(main, {"name": "4K", "path": str(k4)})
        plan = {"kind": "tv", "season": 1, "library_dir": "Series\\Show (2002)",
                "items": [{"source": "a.mkv", "role": "episode", "dest_dir": "Series\\Show (2002)\\Season 1"},
                          {"source": "b.mkv", "role": "episode", "dest_dir": "Series\\Show (2002)\\Specials"}]}
        identify.retarget_library(plan, cfg, str(k4))
        self.assertEqual(plan["library_dir"], "TV Shows\\Show (2002)")
        self.assertEqual([it["dest_dir"] for it in plan["items"]], ["TV Shows\\Show (2002)\\Season 1", "TV Shows\\Show (2002)\\Specials"])

    def test_movies_folder_kept_outside_the_main_library(self):
        main, k4, elsewhere = lib(), lib(), lib()
        cfg = config(main, {"name": "4K", "path": str(k4)}, movies_folder=str(elsewhere))
        plan = movie_plan(cfg)
        self.assertEqual(plan["library_dir"], str(elsewhere) + "\\Some Film (2001)")
        identify.retarget_library(plan, cfg, str(k4))
        self.assertEqual(plan["library_dir"], "Movies\\Some Film (2001)")
        identify.retarget_library(plan, cfg, "")
        self.assertEqual(plan["library_dir"], str(elsewhere) + "\\Some Film (2001)")

    def test_not_once_filing_started_or_for_music(self):
        main, k4 = lib(), lib()
        cfg = config(main, {"name": "4K", "path": str(k4)})
        plan = movie_plan(cfg)
        plan["items"][0]["filed_to"] = "x"
        self.assertTrue(identify.retarget_library(plan, cfg, str(k4)))
        self.assertTrue(identify.retarget_library({"kind": "music", "items": []}, cfg, str(k4)))


class Filing(unittest.TestCase):
    def setUp(self):
        self.old = (review.CFG, review.LIB_ROOT)

    def tearDown(self):
        review.CFG, review.LIB_ROOT = self.old
        review._LIB_CACHE.clear()

    def test_files_go_into_the_chosen_library(self):
        main, k4 = lib("Movies"), lib("Movies")
        review.CFG = config(main, {"name": "4K", "path": str(k4), "formats": ["4k"]})
        review.LIB_ROOT = main
        plan = movie_plan(review.CFG)
        self.assertEqual(review.dest_for(plan["items"][0], plan), main / "Movies" / "Some Film (2001)" / "Some Film (2001).mkv")
        identify.retarget_library(plan, review.CFG, str(k4))
        self.assertEqual(review.root_of(plan), k4)
        self.assertEqual(review.dest_for(plan["items"][0], plan), k4 / "Movies" / "Some Film (2001)" / "Some Film (2001).mkv")
        self.assertEqual(review.dest_for(plan["items"][1], plan).parent, k4 / "Movies" / "Some Film (2001)" / "Featurettes")

    def test_already_there_is_checked_in_the_chosen_library(self):
        main, k4 = lib("Movies"), lib("Movies/Some Film (2001)")
        (k4 / "Movies" / "Some Film (2001)" / "Some Film (2001).mkv").touch()
        review.CFG = config(main, {"name": "4K", "path": str(k4)})
        review.LIB_ROOT = main
        folder = lib()
        for f in ("a.mkv", "b.mkv"):
            (folder / f).write_bytes(b"x")
        plan = movie_plan(review.CFG)
        self.assertFalse([p for p in review.check_plan(folder, plan) if "Already exists" in p])
        identify.retarget_library(plan, review.CFG, str(k4))
        self.assertTrue([p for p in review.check_plan(folder, plan) if "Already exists" in p])

    def test_unreachable_other_library_is_reported(self):
        main = lib("Movies")
        gone = TMP / "unplugged-4k"
        review.CFG = config(main, {"name": "4K", "path": str(gone)})
        review.LIB_ROOT = main
        plan = movie_plan(review.CFG)
        identify.retarget_library(plan, review.CFG, str(gone))
        problems = review.check_plan(lib(), plan)
        self.assertEqual(len(problems), 1)
        self.assertIn(str(gone), problems[0])

    def test_a_4k_disc_is_named_for_the_4k_library(self):
        main, k4 = lib("Movies"), lib("Films")
        review.CFG = config(main, {"name": "4K", "path": str(k4), "formats": ["4k"]})
        review.LIB_ROOT = main
        seen = {}

        def fake_plan(folder, rip, tmdb, index, cfg, override=None):
            seen.update(root=cfg["plex_library_root"], override=override)
            return {"kind": "movie", "library_dir": identify.library_dirs(cfg)["movies"] + "\\X (2000)", "items": []}
        real = identify.plan_folder
        identify.plan_folder = fake_plan
        try:
            folder = lib()
            (folder / "disc_info.json").write_text(json.dumps({"titles": [{"streams": [{"resolution": "3840x2160"}]}]}))
            plan = review.plan_disc(folder)
            self.assertEqual((seen["root"], plan["library_root"], plan["library_dir"]), (str(k4), str(k4), "Films\\X (2000)"))
            (folder / "disc_info.json").write_text(json.dumps({"titles": [{"streams": [{"resolution": "1920x1080"}]}]}))
            plan = review.plan_disc(folder)
            self.assertEqual((seen["root"], plan.get("library_root")), (str(main), None))
            plan = review.plan_disc(folder, override={"tmdb_id": "1"}, root=str(k4))  # "No, pick the right one" keeps the library
            self.assertEqual(plan["library_root"], str(k4))
        finally:
            identify.plan_folder = real

    def test_removed_library_falls_back_to_main_on_the_review_tab(self):
        main, k4 = lib("Movies"), lib("Movies")
        review.CFG = config(main, {"name": "4K", "path": str(k4)})
        review.LIB_ROOT = main
        rip = Path(tempfile.mkdtemp(dir=TMP))
        old_rip = review.RIP_ROOT
        review.RIP_ROOT = rip
        try:
            plan = movie_plan(review.CFG)
            identify.retarget_library(plan, review.CFG, str(k4))
            (rip / "DISC__1").mkdir()
            (rip / "DISC__1" / "plan.json").write_text(json.dumps(plan))
            self.assertEqual(review.list_plans()[0]["library_root"], str(k4))
            review.CFG = {**review.CFG, "multiple_libraries": False}
            got = review.list_plans()[0]
            self.assertNotIn("library_root", got)
            self.assertEqual(got["library_dir"], "Movies\\Some Film (2001)")
        finally:
            review.RIP_ROOT = old_rip


if __name__ == "__main__":
    unittest.main(verbosity=2)
