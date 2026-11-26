"""
test_trouble.py - failures are offered once as an error report, cut to fit, without your user name.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("APPDATA", tempfile.mkdtemp())

import rip_all  # noqa: E402
import trouble  # noqa: E402


class Trouble(unittest.TestCase):
    def setUp(self):
        trouble.PENDING.clear()
        trouble.DONE.clear()
        rip_all.LOG_LINES.clear()

    def test_offered_once_until_dismissed(self):
        a = trouble.record("Rip failed", "ALIEN_D1", "boom")
        self.assertEqual(trouble.record("Rip failed", "ALIEN_D1", "boom"), a)
        self.assertEqual(len(trouble.pending()), 1)
        trouble.dismiss(a)
        trouble.record("Rip failed", "ALIEN_D1", "boom")
        self.assertEqual(trouble.pending(), [])

    def test_preview_has_error_and_disc_log_lines(self):
        rip_all.LOG_LINES.extend(["[10:00:00] E: [ALIEN_D1] scanning disc", "[10:00:01] F: [OTHER] 10%",
                                  "[11:00:00] E: [ALIEN_D1] FINISHED WITH PROBLEMS: 0 saved, 1 failed"])
        trouble.record("Rip didn't finish", "ALIEN_D1", "0 titles saved, 1 failed")
        text = trouble.pending()[0]["preview"]
        self.assertIn("What failed: Rip didn't finish (ALIEN_D1)", text)
        self.assertIn("FINISHED WITH PROBLEMS", text)
        self.assertNotIn("OTHER", text)

    def test_user_name_left_out(self):
        home = str(Path.home())
        trouble.record("Filing didn't finish", "X", f"Couldn't create {home}/Videos/Movies")
        self.assertNotIn(home, trouble.pending()[0]["preview"])

    def test_fits_the_feedback_limit(self):
        rip_all.LOG_LINES.extend([f"[10:00:{i % 60:02}] E: [BIG] line {i} " + "x" * 200 for i in range(300)])
        trouble.record("Rip failed", "BIG", "boom")
        text = trouble.compose(trouble.PENDING[next(iter(trouble.PENDING))], "I clicked Rip")
        self.assertLessEqual(len(text), trouble.LIMIT)
        self.assertIn("What I was doing: I clicked Rip", text)
        self.assertIn("line 299", text)  # the newest lines are kept

    def test_send_unknown(self):
        self.assertIn("error", trouble.send("nope", "", "", {}))



class Logs(unittest.TestCase):
    def rips(self):
        import time
        root = Path(tempfile.mkdtemp())
        for i, label in enumerate(("OBSESSION", "ALIEN_D1", "HEAT")):
            d = root / f"{label}__2026112{i}-120000"
            d.mkdir()
            (d / "makemkv_info.txt").write_text(f'TINFO:0,2,0,"{label}"\nDRV:0,2,999,1,"BD-RE",""\n'
                                                + f"from {Path.home()}\\x\n")
            (d / "rip.log").write_text("saving\n")
            os.utime(d / "makemkv_info.txt", (time.time() + i, time.time() + i))
        return {"output_root": str(root)}

    def text(self, cfg, label=""):
        import base64, gzip
        return gzip.decompress(base64.b64decode(trouble.gather_logs(cfg, label))).decode()

    def test_latest_two_rips(self):
        t = self.text(self.rips())
        self.assertIn("HEAT__", t)
        self.assertIn("ALIEN_D1__", t)
        self.assertNotIn("OBSESSION__", t)
        self.assertNotIn(str(Path.home()), t)  # user name left out

    def test_this_discs_rip_only(self):
        t = self.text(self.rips(), "OBSESSION")
        self.assertIn("OBSESSION__20261120-120000/makemkv_info.txt", t)
        self.assertIn("OBSESSION__20261120-120000/rip.log", t)
        self.assertNotIn("HEAT__", t)

    def test_cut_to_fit(self):
        cfg = self.rips()
        old = trouble.MAX_LOGS
        try:
            trouble.MAX_LOGS = 10
            self.assertEqual(trouble.gather_logs(cfg), "")
        finally:
            trouble.MAX_LOGS = old

    def test_no_rip_folder(self):
        self.assertEqual(trouble.rip_folders({"output_root": ""}), [])


if __name__ == "__main__":
    unittest.main()
