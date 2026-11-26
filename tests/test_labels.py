"""
test_labels.py - what Shelfrip reads from a disc label, and where a TV disc's episodes start
when nothing earlier of the set is filed. From wrong answers in the shared disc database
(2026-11-25): "Season Two" read as no season, "S1D1" not split, "DE" searched for, an episode
range ("27_32") ignored, and disc 4 of a season numbered from e01.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

TMP = discs.setup_env({"tmdb_api_key": "", "use_tvmaze": False})
(TMP / "lib").mkdir()
import identify  # noqa: E402


class Labels(unittest.TestCase):
    def test_labels(self):
        cases = {
            "Landman : Season Two Disc 1": (2, 1, None),
            "The Madison : Season One Disc 2": (1, 2, None),
            "KNIGHT_RIDER_S1D1": (1, 1, None),
            "SAILOR MOON CRYSTAL 27_32": (None, None, (27, 32)),
            "TRANSFORMERS_G1_S2_D7": (2, 7, None),
            "PEACEMAKER_SEASON_1_DISC_2": (1, 2, None),
            "FOOD_WARS_1_2": (None, None, None),        # more likely season 1 disc 2 than episodes 1-2
        }
        for label, (season, disc, eps) in cases.items():
            got = identify.parse_label(label)
            self.assertEqual((got["season"], got["disc"], got.get("episodes")), (season, disc, eps), label)

    def test_queries(self):
        self.assertEqual(identify.parse_label("KNIGHT_RIDER_S1D1")["query"], "Knight Rider")
        self.assertEqual(identify.parse_label("BEAUTY_AND_THE_BEAST_DE")["query"], "Beauty And The Beast")
        self.assertEqual(identify.parse_label("SAILOR MOON CRYSTAL 27_32")["query"], "Sailor Moon Crystal")
        self.assertEqual(identify.parse_label("DAS SCHWEIGEN DER LAEMMER")["query"], "Das Schweigen Der Laemmer")
        self.assertEqual(identify.parse_label("28_YEARS_LATER")["query"], "28 Years Later")

    def test_range_or_season_is_tv(self):
        self.assertTrue(identify.looks_like_tv([], identify.parse_label("SAILOR MOON CRYSTAL 27_32"), None))
        self.assertTrue(identify.looks_like_tv([], identify.parse_label("KNIGHT_RIDER_S1D1"), None))


class FakeTMDB:
    """A show with seasons of 14, 12 and 13 episodes, 45 minutes each."""
    SEASONS = {1: 14, 2: 12, 3: 13}

    def search(self, kind, q):
        return [{"id": 1, "name": "Show", "first_air_date": "2014-01-01"}]

    def tv(self, tid):
        return {"id": 1, "name": "Show", "first_air_date": "2014-01-01",
                "seasons": [{"season_number": 0, "episode_count": 3}] +
                           [{"season_number": n, "episode_count": c} for n, c in self.SEASONS.items()]}

    def season(self, tid, n):
        return {"episodes": [{"episode_number": e, "name": f"S{n} Ep {e}", "runtime": 45}
                             for e in range(1, self.SEASONS.get(n, 0) + 1)]}


def episodes(label, n=5, minutes=45):
    titles = [{"title_id": i, "output_file": f"t{i:02d}.mkv", "duration_seconds": minutes * 60 + i,
               "size_bytes": 1_000_000_000, "chapters": 8, "streams": []} for i in range(n)]
    disc = {"titles": titles, "disc_label": label}
    folder = TMP / "rip" / f"{label}__1"
    folder.mkdir(parents=True, exist_ok=True)
    lib = identify.index_library(TMP / "lib", identify.load_config())
    warnings = []
    plan = identify.plan_tv(folder, TMP / "rip", disc, titles, identify.parse_label(label), FakeTMDB(), lib, None,
                            identify.load_config(), warnings)
    eps = [(it["season"], it["episodes"][0] if it.get("episodes") else it["episode"]) for it in plan["items"]
           if it["role"] == "episode"]
    return plan, eps, warnings


class FirstEpisode(unittest.TestCase):
    def test_episode_range_finds_its_season(self):
        plan, eps, warnings = episodes("SAILOR_RANGE 27_31", n=5)
        self.assertEqual(eps, [(3, e) for e in range(1, 6)])  # 14 + 12 episodes before season 3
        self.assertNotIn("Assumed Season 1", " ".join(warnings))
        plan, eps, warnings = episodes("SAILOR_LATER 33_37", n=5)
        self.assertEqual(eps, [(3, e) for e in range(7, 12)])
        self.assertEqual(plan["season"], 3)

    def test_disc_number_guesses_the_start(self):
        plan, eps, warnings = episodes("PEACE_SEASON_1_DISC_2", n=4)
        self.assertEqual([e for _, e in eps], [5, 6, 7, 8])
        self.assertIn("guessed from the disc number", " ".join(warnings))

    def test_disc_one_starts_at_one(self):
        plan, eps, warnings = episodes("PEACE_B_SEASON_1_DISC_1", n=4)
        self.assertEqual([e for _, e in eps], [1, 2, 3, 4])

    def test_guess_past_the_season_is_not_made(self):
        plan, eps, warnings = episodes("LONG_SEASON_1_DISC_9", n=4)  # 9 * 4 > 14 episodes
        self.assertNotIn("guessed from the disc number", " ".join(warnings))


if __name__ == "__main__":
    unittest.main()
