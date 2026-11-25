"""
test_epmatch.py - matching a disc's videos to episodes from their subtitles (epmatch.py, and the
TV part of subcheck.py), with no internet: TMDB and OpenSubtitles are faked.
"""

from __future__ import annotations

import itertools
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

TMP = discs.setup_env({"tmdb_api_key": "", "use_community": False, "use_thediscdb": False})
import epmatch  # noqa: E402
import refsubs  # noqa: E402
import subcheck  # noqa: E402


# ------------------------------------------------------------------ fake seasons

def vocab(seed: int, n: int = 60) -> list[str]:
    rnd = random.Random(seed)
    return ["".join(rnd.choice("bcdfghjklmnprstvwz") + rnd.choice("aeiou") for _ in range(3)) for _ in range(n)]


COMMON = "i don't know what you mean|are you okay|come on let's go|what are you doing here|we need to talk".split("|")


def dialogue(ep: int, lines: int = 200, seed: int = 0) -> list[str]:
    """Lines an episode's characters say: everyday phrases plus the episode's own words."""
    rnd = random.Random(ep * 1000 + seed)
    words = vocab(ep)
    out = []
    for _ in range(lines):
        if rnd.random() < 0.25:
            out.append(rnd.choice(COMMON))
        else:
            out.append(" ".join(rnd.choice(words) for _ in range(rnd.randint(4, 9))))
    return out


def srt(lines: list[str]) -> str:
    return "\n\n".join(f"{k + 1}\n00:00:{k % 60:02d},000 --> 00:00:{k % 60:02d},900\n{ln}" for k, ln in enumerate(lines))


class FakeTMDB:
    """A 10-episode season whose summaries name each episode's guest, and e09 is a clip show."""

    def __init__(self, n=10, clip=9):
        self.n, self.clip = n, clip

    def season(self, tid, season):
        eps = []
        for e in range(1, self.n + 1):
            guest = vocab(e)[0].capitalize()
            ov = (f"The gang looks back at their favourite moments." if e == self.clip
                  else f"{guest} arrives with news about the {vocab(e)[1]} and the {vocab(e)[2]}.")
            eps.append({"episode_number": e, "name": f"Episode Title {vocab(e)[3].capitalize()}",
                        "overview": ov, "guest_stars": [{"character": guest}]})
        return {"episodes": eps}


def unit(source, episode, text, action="move"):
    item = {"source": source, "episode": episode, "action": action, "name": f"Show - s01e{episode:02d}"}
    return {"item": item, "episode": episode, "label": source, "text": text,
            "row": {"title": source, "track": "pgs eng", "episode": episode}}


# ------------------------------------------------------------------ tests

class Hungarian(unittest.TestCase):
    def test_matches_brute_force(self):
        rnd = random.Random(7)
        for _ in range(40):
            n, m = rnd.randint(1, 5), rnd.randint(5, 7)
            cost = [[rnd.random() for _ in range(m)] for _ in range(n)]
            got = epmatch.hungarian(cost)
            self.assertEqual(len(set(got)), n)
            best = min(sum(cost[i][p[i]] for i in range(n)) for p in itertools.permutations(range(m), n))
            self.assertAlmostEqual(sum(cost[i][got[i]] for i in range(n)), best, places=9)

    def test_more_videos_than_episodes_leaves_the_worst_out(self):
        scores = {"a": {1: 5.0, 2: 1.0}, "b": {1: 4.0, 2: 0.5}, "c": {1: 0.2, 2: 3.0}}
        self.assertEqual(epmatch.best_pairs(scores, ["a", "b", "c"], [1, 2]), {"a": 1, "c": 2})


class Assign(unittest.TestCase):
    def test_two_videos_cannot_take_the_same_episode(self):
        scores = {0: {1: 3.0, 2: 2.8}, 1: {1: 3.2, 2: 1.0}}
        r = epmatch.assign(scores, {0: 1, 1: 2}, prior=0)
        self.assertEqual((r[0]["episode"], r[1]["episode"]), (2, 1))

    def test_weak_evidence_keeps_the_planned_numbers(self):
        scores = {0: {1: 1.00, 2: 1.05, 3: 0.2}, 1: {1: 1.0, 2: 1.1, 3: 0.9}}
        r = epmatch.assign(scores, {0: 1, 1: 2})
        self.assertEqual((r[0]["episode"], r[1]["episode"]), (1, 2))

    def test_clip_show_does_not_steal_a_real_episode(self):
        # video 2 is the clip show: it fits e1-e5 nearly as well as e5 itself does
        scores = {0: {1: 4.0, 5: 0.1, 6: 0.1}, 1: {1: 0.1, 5: 3.0, 6: 0.2},
                  2: {1: 3.6, 2: 3.4, 3: 3.5, 4: 3.3, 5: 3.7, 6: 0.6}}
        r = epmatch.assign(scores, {0: 1, 1: 5, 2: 6}, clip_eps={6})
        self.assertEqual(r[2]["episode"], 6)
        self.assertTrue(r[2]["clip_show"])
        self.assertEqual(r[1]["episode"], 5)

    def test_clip_show_words(self):
        self.assertTrue(epmatch.is_clip_show("The Highlights of 100", ""))
        self.assertTrue(epmatch.is_clip_show("The One With All the Memories", "The friends look back on ten years."))
        self.assertFalse(epmatch.is_clip_show("The Pilot", "Jerry and George discuss a show about nothing."))


class Reference(unittest.TestCase):
    def test_dialogue_finds_its_episode(self):
        refs = {e: epmatch.shingles(epmatch.srt_text(srt(dialogue(e)))) for e in range(1, 9)}
        sample = "\n".join(dialogue(4)[::3])            # a third of e04's lines, as OCR would read them
        sc = epmatch.reference_scores(sample, refs)
        self.assertEqual(max(sc, key=sc.get), 4)
        self.assertGreater(sc[4], 5 * max(v for e, v in sc.items() if e != 4) + 1)

    def test_srt_text_drops_numbers_times_and_tags(self):
        raw = "1\n00:00:01,000 --> 00:00:02,000\n<i>Hello there</i>\n\n2\n00:00:03,000 --> 00:00:04,000\n(LAUGHS) - Bye now"
        self.assertEqual(epmatch.srt_text(raw), "Hello there\nBye now")

    def test_mislabeled_reference_is_dropped(self):
        refs = {e: epmatch.shingles("\n".join(dialogue(e))) for e in (1, 2, 3)}
        refs[3] = epmatch.shingles("\n".join(dialogue(2, seed=1) + dialogue(2)))   # e03's file is really e02
        self.assertEqual(epmatch.mislabeled(refs), {2, 3})

    def test_wanted_episodes(self):
        self.assertEqual(refsubs.wanted_episodes([3, 4], list(range(1, 11)), {9}), [3, 4, 2, 5, 1, 6, 9])


class Judge(unittest.TestCase):
    """The TV part of the subtitle check, end to end with fake TMDB and OpenSubtitles."""

    def run_judge(self, disc, cfg=None, imported=False, refs_for=range(1, 11)):
        plan = {"tmdb_id": "123", "season": 1}
        todo = [unit(f"t{k:02d}.mkv", planned, "\n".join(text)) for k, (planned, text) in enumerate(disc)]
        report = {"findings": []}
        real = refsubs.fetch
        refsubs.fetch = lambda cfg, show, season, eps, lang, log=print, **kw: \
            {e: srt(dialogue(e)) for e in eps if e in refs_for}
        try:
            subcheck._judge_tv(plan, todo, FakeTMDB(), report, lambda *a: None, cfg or {}, imported)
        finally:
            refsubs.fetch = real
        return report, [u["row"] for u in todo]

    def test_shuffled_files_with_reference_subtitles(self):
        # an imported folder: files planned as e01-e05 in name order, really e03, e01, e05, e02, e04
        truth = [3, 1, 5, 2, 4]
        disc = [(k + 1, dialogue(e)[::4]) for k, e in enumerate(truth)]
        report, rows = self.run_judge(disc, {"reference_subtitles": True}, imported=True)
        self.assertEqual([r["best_episode"] for r in rows], truth)
        self.assertTrue(all(r["by_reference"] for r in rows))
        self.assertEqual(sum("looks like" in r["verdict"] for r in rows), 5)   # none were where planned

    def test_right_disc_stays_right(self):
        disc = [(e, dialogue(e)[::4]) for e in (4, 5, 6, 7)]
        report, rows = self.run_judge(disc, {"reference_subtitles": True})
        self.assertEqual([r["verdict"] for r in rows], ["fits"] * 4)
        self.assertEqual(report["findings"], [])

    def test_clip_show_with_reference_subtitles(self):
        clip = dialogue(9, lines=60) + [ln for e in range(1, 7) for ln in dialogue(e)[:25]]
        disc = [(7, dialogue(7)[::4]), (8, dialogue(8)[::4]), (9, clip[::2])]
        report, rows = self.run_judge(disc, {"reference_subtitles": True})
        self.assertEqual([r["best_episode"] for r in rows], [7, 8, 9])
        self.assertIn("clip show", rows[2]["verdict"])
        self.assertEqual(report["findings"], [])

    def test_without_reference_subtitles_uses_plot_words(self):
        # no download: OCR text that says each episode's guest name and summary words
        disc = [(2, [f"{vocab(e)[0].capitalize()} brought the {vocab(e)[1]} and the {vocab(e)[2]}"] * 3)
                for e in (3, 2)]
        report, rows = self.run_judge(disc, {})
        self.assertEqual([r["best_episode"] for r in rows], [3, 2])
        self.assertFalse(rows[0]["by_reference"])


class ReviewTab(unittest.TestCase):
    """The check runs in the background after naming, and holds back automatic filing."""

    def test_background_check_and_auto_file_hold(self):
        import json
        import review
        import subcheck as sc
        folder = review.RIP_ROOT / "SHOW_S1_D1"
        folder.mkdir(parents=True, exist_ok=True)
        plan = {"kind": "tv", "tmdb_id": "123", "season": 1, "status": "proposed", "title": "Show",
                "match_source": "existing library folder", "warnings": [],
                "items": [{"source": "t00.mkv", "role": "episode", "episode": 1, "episodes": [1], "action": "move",
                           "name": "Show - s01e01"}]}
        review.save_plan(folder, plan)
        (folder / "disc_info.json").write_text("{}", encoding="utf-8")
        review.CFG["subtitle_check"] = True
        real = sc.check_folder
        sc.check_folder = lambda folder, cfg, tmdb, exe, langs, log=print, **kw: {
            "findings": ["t00.mkv is planned as e01 but its dialogue fits e02 Two better (40% ...)."],
            "titles": [{"source": "t00.mkv", "part": None, "episode": 1, "verdict": "looks like e02",
                        "best_episode": 2, "best_name": "Two", "by_reference": True, "reference_share": 0.4,
                        "text": "the whole OCR text"}]}
        try:
            first = review.list_plans()[0]
            self.assertIn(first["subcheck"]["state"], ("queued", "running", "done"))
            review.SUBCHECK["thread"].join(10)
            p = review.list_plans()[0]
        finally:
            sc.check_folder = real
            review.CFG["subtitle_check"] = False
        self.assertEqual(p["subcheck"]["state"], "done")
        self.assertEqual(p["subcheck"]["titles"][0]["best_episode"], 2)
        self.assertIn("the subtitles disagree with an episode number", review.confidence(p))
        saved = json.loads((folder / "subcheck.json").read_text(encoding="utf-8"))
        self.assertNotIn("text", saved["titles"][0])
        review.save_plan(folder, p)   # the view is never written into plan.json
        self.assertNotIn("subcheck", json.loads((folder / "plan.json").read_text(encoding="utf-8")))
        # another show or season planned now: the old check doesn't count
        p["tmdb_id"] = "999"
        self.assertIsNone(review.subcheck_report(folder, p))


if __name__ == "__main__":
    unittest.main()
