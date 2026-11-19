"""
test_paths.py - old copies of your settings next to the program are merged and moved aside.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = """CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE discs (id INTEGER PRIMARY KEY, content_hash TEXT, disc_label TEXT, title TEXT, tmdb_id TEXT);
CREATE TABLE titles (disc_id INTEGER, title_index INTEGER, name TEXT);"""


def db(path: Path, discs: list[tuple]) -> None:
    c = sqlite3.connect(path)
    c.executescript(SCHEMA)
    for i, (label, title, tid) in enumerate(discs, 1):
        c.execute("INSERT INTO discs VALUES (?, '', ?, ?, ?)", (i, label, title, tid))
        c.execute("INSERT INTO titles VALUES (?, 0, ?)", (i, title))
    c.commit()
    c.close()


class OldCopies(unittest.TestCase):
    def test_merge_and_move(self):
        t = Path(tempfile.mkdtemp())
        app, data = t / "app", t / "data"
        (app / ".cache").mkdir(parents=True)
        (data / ".cache").mkdir(parents=True)
        shutil.copy2(ROOT / "paths.py", app / "paths.py")
        (app / "config.json").write_text("{}")
        (data / "config.json").write_text('{"a": 1}')
        db(app / "disc_catalog.db", [("ONE", "One", "1"), ("OLD_ONLY", "Old", "2")])
        db(data / "disc_catalog.db", [("ONE", "One", "1"), ("NEW", "New", "3")])
        (app / "learned_labels.json").write_text(json.dumps({"ONE": {"tmdb_id": "1"}, "OLD ONLY": {"tmdb_id": "2"}}))
        (data / "learned_labels.json").write_text(json.dumps({"ONE": {"tmdb_id": "1"}, "NEW": {"tmdb_id": "3"}}))
        env = {**os.environ, "SHELFRIP_DATA": str(data)}
        out = subprocess.run([sys.executable, "-c", "import paths; print(paths.MIGRATION_NOTE)"], cwd=app, env=env,
                             capture_output=True, text=True, check=True).stdout
        self.assertIn("Old settings (not used)", out)
        old = app / "Old settings (not used)"
        self.assertTrue((old / "config.json").exists() and (old / "disc_catalog.db").exists())
        self.assertFalse((app / "config.json").exists())
        labels = json.loads((data / "learned_labels.json").read_text())
        self.assertEqual(set(labels), {"ONE", "NEW", "OLD ONLY"})
        c = sqlite3.connect(data / "disc_catalog.db")
        self.assertEqual(sorted(r[0] for r in c.execute("SELECT disc_label FROM discs")), ["NEW", "OLD_ONLY", "ONE"])
        self.assertEqual(c.execute("SELECT COUNT(*) FROM titles").fetchone()[0], 3)
        # a second start does nothing
        out2 = subprocess.run([sys.executable, "-c", "import paths; print(repr(paths.MIGRATION_NOTE))"], cwd=app,
                              env=env, capture_output=True, text=True, check=True).stdout
        self.assertEqual(out2.strip(), "''")


if __name__ == "__main__":
    unittest.main()
