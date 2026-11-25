"""
test_learned.py - labels remembered from filed discs: a film's sequel isn't taken for the film
(tester report on 1.0.1: THE_SANTA_CLAUSE_2 was recognised as The Santa Clause and skipped as
already ripped), while TV sets still continue from the disc before.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

discs.setup_env({"tmdb_api_key": ""})
import discdb  # noqa: E402


def movie(title, tmdb):
    return {"kind": "movie", "title": title, "year": "1994", "tmdb_id": tmdb, "items": []}


def show(season, last):
    return {"kind": "tv", "title": "Friends", "year": "1994", "tmdb_id": "1668", "season": season,
            "items": [{"role": "episode", "action": "move", "season": season, "episodes": [last]}]}


class Learned(unittest.TestCase):
    def setUp(self):
        discdb.LEARNED.unlink(missing_ok=True)

    def test_sequel_is_not_the_film(self):
        discdb.remember("THE_SANTA_CLAUSE", movie("The Santa Clause", "8871"))
        self.assertIsNone(discdb.learned("THE_SANTA_CLAUSE_2"))
        self.assertEqual(discdb.learned("THE_SANTA_CLAUSE")["tmdb_id"], "8871")

    def test_filing_the_sequel_keeps_the_film(self):
        discdb.remember("THE_SANTA_CLAUSE", movie("The Santa Clause", "8871"))
        discdb.remember("THE_SANTA_CLAUSE_2", movie("The Santa Clause 2", "11395"))
        self.assertEqual(discdb.learned("THE_SANTA_CLAUSE")["tmdb_id"], "8871")
        self.assertEqual(discdb.learned("THE_SANTA_CLAUSE_2")["tmdb_id"], "11395")

    def test_tv_disc_number_still_continues(self):
        discdb.remember("FRIENDS_S1_1", show(1, 6))
        hit = discdb.learned("FRIENDS_S1_2")
        self.assertEqual((hit["kind"], hit["season"], hit["last_episode"]), ("tv", 1, 6))

    def test_disc_markers_still_match_films(self):
        discdb.remember("ALIEN_D1", movie("Alien", "348"))
        self.assertEqual(discdb.learned("ALIEN_D2")["tmdb_id"], "348")

    def test_old_entries_still_found(self):
        discdb.LEARNED.write_text('{"TOY STORY": {"kind": "movie", "tmdb_id": "862"}}', encoding="utf-8")
        self.assertEqual(discdb.learned("TOY_STORY")["tmdb_id"], "862")
        self.assertIsNone(discdb.learned("TOY_STORY_3"))


if __name__ == "__main__":
    unittest.main()
