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


if __name__ == "__main__":
    unittest.main(verbosity=2)
