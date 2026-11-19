"""
test_naming.py - every recorded disc must still be named exactly the same way.

Runs with no internet: the web answers come from fixtures/http.json. If a change is meant to
rename things, run record.py again and commit the new expected.json files.
"""

from __future__ import annotations

import json
import sys
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402
import net  # noqa: E402

CASES = sorted(p.parent for p in discs.FIXTURES.glob("*/expected.json"))


@unittest.skipUnless(CASES, "no recorded discs (run tests/record.py)")
class Naming(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cfg = json.loads((discs.FIXTURES / "config.json").read_text(encoding="utf-8"))
        cls.tmp = discs.setup_env(cfg)
        cls.player = net.Player(json.loads((discs.FIXTURES / "http.json").read_text(encoding="utf-8")))
        cls.real = urllib.request.urlopen
        urllib.request.urlopen = cls.player
        import time
        cls.sleep, time.sleep = time.sleep, lambda s: None  # no waiting between "retries" offline

    @classmethod
    def tearDownClass(cls):
        import time
        urllib.request.urlopen = cls.real
        time.sleep = cls.sleep

    def test_discs(self):
        for fix in CASES:
            with self.subTest(disc=fix.name):
                folder = discs.lay_out(fix, self.tmp / "rip")
                got = discs.name_disc(folder, self.tmp / "rip", "test-key")
                want = json.loads((fix / "expected.json").read_text(encoding="utf-8"))
                self.assertEqual(want, got)


if __name__ == "__main__":
    unittest.main()
