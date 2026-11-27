"""
test_filing.py - a filing must never get stuck at "starting": a worker that dies or never starts
is noticed, a stuck filing can be stopped, and stopping leaves the disc ready to file or discard.

Run on its own (python tests/test_filing.py): Shelfrip reads its settings when first imported.
"""

from __future__ import annotations

import json
import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

TMP = discs.setup_env({"tmdb_api_key": "", "eject_after_filing": False, "media_server": "plex"})
(TMP / "lib").mkdir()
import review  # noqa: E402


IDS = iter(range(100, 1000))


def make_disc(name: str) -> tuple[Path, dict]:
    t = next(IDS)  # each its own film, so none is "already in the library"
    d = TMP / "rip" / name
    d.mkdir()
    (d / "disc_info.json").write_text("{}")
    (d / "a.mkv").write_bytes(b"x" * 1000)
    lib = f"Movies\\{name} (2000) {{tmdb-{t}}}"
    plan = {"kind": "movie", "title": name, "year": "2000", "tmdb_id": str(t), "status": "proposed", "format": "DVD",
            "disc_label": name, "library_dir": lib,
            "items": [{"source": "a.mkv", "action": "move", "role": "main", "dest_dir": lib,
                       "name": f"{name} (2000) {{tmdb-{t}}}"}]}
    review.save_plan(d, plan)
    return d, json.loads((d / "plan.json").read_text())


def wait(name: str, secs=10) -> dict:
    end = time.time() + secs
    while time.time() < end and review.JOBS[name].get("state") == "running":
        time.sleep(0.05)
    return review.JOBS[name]


class Stuck(unittest.TestCase):
    def test_plan_save_failing_at_start_doesnt_leave_it_running(self):
        """The reported bug: the plan couldn't be saved just after the job was registered, so it sat
        at "starting" with no worker for hours and blocked every other filing."""
        d, plan = make_disc("SAVEFAIL")
        real, calls = review.save_plan, []

        def flaky(folder, p):
            calls.append(1)
            if "filing" in p:  # the save that marks it as being filed
                raise PermissionError(13, "The process cannot access the file")
            real(folder, p)
        review.save_plan = flaky
        try:
            problems = review.start_filing(d, plan)
        finally:
            review.save_plan = real
        self.assertTrue(problems and "Couldn't start filing" in problems[0], problems)
        self.assertEqual(review.JOBS["SAVEFAIL"]["state"], "error")
        self.assertFalse(any(j.get("state") == "running" for j in review.JOBS.values()))
        # and filing it again works
        self.assertEqual(review.start_filing(d, json.loads((d / "plan.json").read_text())), [])
        self.assertEqual(wait("SAVEFAIL")["state"], "done")

    def test_save_plan_waits_out_a_brief_lock(self):
        d, plan = make_disc("LOCKED")
        real, n = review.os.replace, [0]

        def busy(a, b):
            n[0] += 1
            if n[0] < 3:
                raise PermissionError(5, "Access is denied")
            real(a, b)
        review.os.replace = busy
        try:
            review.save_plan(d, dict(plan, title="Changed"))
        finally:
            review.os.replace = real
        self.assertEqual(json.loads((d / "plan.json").read_text())["title"], "Changed")

    def test_job_with_no_worker_is_reaped(self):
        review.JOBS["GHOST"] = {"state": "running", "current": "starting", "done_bytes": 0, "total_bytes": 0}
        review.reap_jobs()
        self.assertEqual(review.JOBS["GHOST"]["state"], "error")
        self.assertIn("file it again", review.JOBS["GHOST"]["current"])

    def test_worker_that_dies_is_reaped(self):
        d, plan = make_disc("DIES")
        real = review.file_job
        review.file_job = lambda folder, p: (_ for _ in ()).throw(SystemExit())  # dies without a normal error
        try:
            self.assertEqual(review.start_filing(d, plan), [])
            review.THREADS["DIES"].join(5)
        finally:
            review.file_job = real
        review.reap_jobs()
        self.assertEqual(review.JOBS["DIES"]["state"], "error")

    def test_stop_a_stuck_filing(self):
        d, plan = make_disc("STOPME")
        real, gate = review.file_job, threading.Event()

        def hangs(folder, p):  # stuck partway: only notices Stop at its next step
            job = review.JOBS[folder.name]
            try:
                while not gate.wait(0.05):
                    review._beat(job)
            except Exception as exc:
                review._job_failed(folder, p, job, exc)
        review.file_job = hangs
        try:
            self.assertEqual(review.start_filing(d, plan), [])
            self.assertEqual(review.JOBS["STOPME"]["state"], "running")
            view = review.job_view(review.JOBS["STOPME"])
            self.assertIn("idle", view)
            self.assertEqual(review.stop_filing(d), "")
            review.THREADS["STOPME"].join(5)
        finally:
            gate.set()
            review.file_job = real
        job = review.JOBS["STOPME"]
        self.assertEqual(job["state"], "error")
        self.assertIn("Filing stopped", job["current"])
        saved = json.loads((d / "plan.json").read_text())
        self.assertNotIn("filing", saved)  # not picked up again by itself
        self.assertTrue(saved.get("hold"))  # nor filed automatically
        self.assertTrue((d / "a.mkv").exists())  # nothing lost
        self.assertEqual(review.stop_filing(d), "This disc isn't being filed.")
        # file it again: it goes through
        self.assertEqual(review.start_filing(d, saved), [])
        self.assertEqual(wait("STOPME")["state"], "done")

    def test_stop_mid_copy_removes_the_partial(self):
        src = TMP / "big.mkv"
        src.write_bytes(b"y" * (20 * 1024 * 1024))
        dst = TMP / "lib" / "copy" / "big.mkv"
        job = {"state": "running", "done_bytes": 0, "stop": True}
        real = review.same_volume
        review.same_volume = lambda a, b: False
        try:
            with self.assertRaises(review.Stopped):
                review.copy_with_progress(src, dst, job)
        finally:
            review.same_volume = real
        self.assertFalse(dst.exists())
        self.assertFalse(dst.with_name(dst.name + ".partial").exists())
        self.assertTrue(src.exists())


class SplitResume(unittest.TestCase):
    def test_failed_split_keeps_the_episodes_already_filed(self):
        """Fairy Tail, 2026-11-26: cutting the last episode failed after e02-e05 were in the library.
        Filing again said they were "already in Plex" and set the whole video to Skip."""
        import split
        name = "SPLITFAIL"
        d = TMP / "rip" / name
        d.mkdir()
        (d / "disc_info.json").write_text("{}")
        (d / "b.mkv").write_bytes(b"x" * 1000)
        lib = "TV Shows\\DVD\\Splitshow (2009) {tmdb-777}"
        names = [f"Splitshow (2009) - s02e0{k} - Ep {k}" for k in (1, 2, 3)]
        plan = {"kind": "tv", "title": "Splitshow", "year": "2009", "tmdb_id": "777", "season": 2, "status": "proposed",
                "format": "DVD", "disc_label": name, "library_dir": lib,
                "items": [{"source": "b.mkv", "action": "move", "role": "episode", "season": 2, "episodes": [1, 2, 3],
                           "needs_split": True, "dest_dir": lib + "\\Season 2", "name": "Splitshow (2009) - s02e01-e03",
                           "split": {"chapters": [0, 100, 200], "starts": [0, 1, 2], "total": 300, "names": names}}]}
        review.save_plan(d, plan)
        cut, fail = [], {"on": 2}

        def fake_cut(src, sp, k, out, cfg, title=""):
            if k == fail["on"]:
                raise RuntimeError(f"episode {k + 1} came out 7345s long, expected 100s")
            cut.append(k)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"e" * 10)
            return out
        real = (split.cut, split.tag_audio, split.set_default_tracks, split.available)
        split.cut, split.tag_audio, split.set_default_tracks = fake_cut, lambda *a: "", lambda *a: ""
        split.available = lambda cfg: True
        try:
            self.assertEqual(review.start_filing(d, json.loads((d / "plan.json").read_text())), [])
            self.assertEqual(wait(name)["state"], "error")
            plan = json.loads((d / "plan.json").read_text())
            self.assertEqual(len(plan["items"][0]["filed_to"]), 2)  # e01 and e02 noted as this disc's own
            self.assertFalse(review.item_done(plan["items"][0]))
            fail["on"] = None
            self.assertEqual(review.start_filing(d, plan), [])  # not "already in Plex", not "already exists"
            self.assertEqual(wait(name)["state"], "done")
            self.assertEqual(cut, [0, 1, 2])  # only e03 was cut the second time
        finally:
            split.cut, split.tag_audio, split.set_default_tracks, split.available = real


class StartOver(unittest.TestCase):
    def test_start_naming_over(self):
        d, plan = make_disc("AGAIN")
        plan["items"][0]["name"] = "My Edit"
        plan["edited"] = True
        review.save_plan(d, plan)
        fresh = {"kind": "movie", "title": "Fresh", "year": "2001", "tmdb_id": "9", "status": "proposed", "items": []}
        real = review.identify.plan_folder
        review.identify.plan_folder = lambda *a, **k: dict(fresh)
        review.JOBS["AGAIN"] = {"state": "error", "current": "old problem"}
        try:
            r = review.start_over(d)
        finally:
            review.identify.plan_folder = real
        self.assertEqual(r["plan"]["title"], "Fresh")
        self.assertEqual(r["plan"]["folder"], "AGAIN")
        saved = json.loads((d / "plan.json").read_text())
        self.assertNotIn("edited", saved)
        self.assertTrue(saved["hold"])
        self.assertEqual(json.loads((d / "plan.old.json").read_text())["items"][0]["name"], "My Edit")
        self.assertNotIn("AGAIN", review.JOBS)

    def test_not_while_filing_or_part_filed(self):
        d, plan = make_disc("BUSY")
        review.JOBS["BUSY"] = {"state": "running"}
        review.THREADS["BUSY"] = threading.Thread(target=threading.Event().wait, args=(1,), daemon=True)
        review.THREADS["BUSY"].start()
        self.assertIn("being filed", review.start_over(d)["error"])
        review.THREADS["BUSY"].join(2)
        review.JOBS["BUSY"] = {"state": "error"}
        plan["items"][0]["filed_to"] = str(TMP / "x.mkv")
        review.save_plan(d, plan)
        self.assertIn("already in your library", review.start_over(d)["error"])


class EpisodeStyle(unittest.TestCase):
    def test_upper_codes_only_when_chosen(self):
        n = review.naming
        self.assertEqual(n.episode_code({}, "Show (2001) - s01e02 - Pilot"), "Show (2001) - s01e02 - Pilot")
        up = {"episode_style": "upper"}
        self.assertEqual(n.episode_code(up, "Show (2001) - s01e02 - Pilot"), "Show (2001) - S01E02 - Pilot")
        self.assertEqual(n.episode_code(up, "Show (2001) - s01e02-e03"), "Show (2001) - S01E02-E03")
        self.assertEqual(n.episode_code(up, "Show (2001) - s01e02-featurette"), "Show (2001) - S01E02-featurette")
        self.assertEqual(n.episode_code(up, "Making Of"), "Making Of")

    def test_filed_name_uses_the_setting(self):
        it = {"name": "Show (2001) - s01e02 - Pilot", "dest_dir": "TV Shows\\Show (2001)\\Season 1", "role": "episode"}
        self.assertTrue(review.dest_for(it).name.endswith("- s01e02 - Pilot.mkv"))
        review.CFG["episode_style"] = "upper"
        try:
            self.assertTrue(review.dest_for(it).name.endswith("- S01E02 - Pilot.mkv"))
        finally:
            review.CFG.pop("episode_style")


if __name__ == "__main__":
    unittest.main(verbosity=2)
