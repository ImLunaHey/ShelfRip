"""
test_feedback_logs.py - recent logs sent with "Something's wrong" and "Other" feedback (never with
ideas, and never with keys or the Windows user name in them), and the box-art guess from a disc label.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

discs.setup_env({"tmdb_api_key": ""})
import app  # noqa: E402
import community  # noqa: E402


class Scrub(unittest.TestCase):
    def test_removes_keys_tokens_and_home(self):
        home = str(Path.home())
        cfg = {"tmdb_api_key": "abcdef123456", "plex_token": "plexsecret99", "output_root": "E:\\Ripped"}
        text = (f"GET /3/movie/603?api_key=zzzz9999 failed\nX-Plex-Token=qqqq1111&x=1\n"
                f"Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.abc\nkey abcdef123456 and plexsecret99\n{home}\\Videos")
        out = app.scrub(text, cfg)
        for secret in ("zzzz9999", "qqqq1111", "eyJhbGciOiJIUzI1NiJ9", "abcdef123456", "plexsecret99", home):
            self.assertNotIn(secret, out)
        self.assertIn("E:\\Ripped", app.scrub("into E:\\Ripped", cfg))
        self.assertIn("~", out)

    def test_logs_fit_and_are_scrubbed(self):
        with mock.patch.object(app.rip_all, "LOG_LINES", [f"line {i} api_key=sekrit{i}" for i in range(5000)]), \
             mock.patch.object(app, "setup_check", lambda: [{"name": "MakeMKV", "ok": True, "detail": "found"}]):
            logs = app.feedback_logs()
        self.assertLessEqual(len(logs), app.FEEDBACK_LOG_LIMIT)
        self.assertIn("MakeMKV: ok", logs)
        self.assertIn("line 4999", logs)
        self.assertNotIn("sekrit", logs)


class Send(unittest.TestCase):
    def sent(self, kind: str, logs: str) -> dict:
        got = {}
        with mock.patch.object(community, "base_url", lambda cfg: "https://db.test"), \
             mock.patch.object(community, "_http", lambda url, body: got.update(body) or {}):
            self.assertEqual(community.send_feedback({"kind": kind, "title": "t", "logs": logs}, {}), {"ok": True})
        return got

    def test_logs_only_for_problem_and_other(self):
        self.assertEqual(self.sent("problem", "abc")["logs"], "abc")
        self.assertEqual(self.sent("other", "abc")["logs"], "abc")
        self.assertNotIn("logs", self.sent("idea", "abc"))
        self.assertNotIn("logs", self.sent("problem", ""))


class LabelGuess(unittest.TestCase):
    class Fake:
        def __init__(self, movies=(), shows=()):
            self.movies, self.shows, self.asked = list(movies), list(shows), []

        def search(self, kind, query):
            self.asked.append((kind, query))
            return self.movies if kind == "movie" else self.shows

    def test_tv_label_with_season(self):
        t = self.Fake(shows=[{"id": 1399, "name": "Game of Thrones", "first_air_date": "2011-04-17"}])
        g = app.label_guess("GAME_OF_THRONES_S2_D1", t)
        self.assertEqual((g["kind"], g["tmdb_id"], g["season"]), ("tv", "1399", 2))
        self.assertEqual(t.asked[0], ("tv", "Game Of Thrones"))

    def test_movie_year_picks_that_release(self):
        t = self.Fake(movies=[{"id": 620, "title": "Ghostbusters", "release_date": "1984-06-08"},
                              {"id": 43074, "title": "Ghostbusters", "release_date": "2016-07-14"}])
        g = app.label_guess("GHOSTBUSTERS_2016", t)
        self.assertEqual((g["kind"], g["tmdb_id"], g["year"]), ("movie", "43074", "2016"))

    def test_no_guess_without_a_name_or_tmdb(self):
        self.assertIsNone(app.label_guess("DISC_1", self.Fake(movies=[{"id": 1, "title": "x"}])))
        self.assertIsNone(app.label_guess("MATRIX", None))


if __name__ == "__main__":
    unittest.main()
