"""
test_label_guess.py - the box-art guess from a disc label, shown on the drive card before ripping.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

discs.setup_env({"tmdb_api_key": ""})
import app  # noqa: E402


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
