"""DVD fingerprint recipe and compatibility; no physical disc or video reads."""
import hashlib
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs
TMP = discs.setup_env({})
import discdb


def digest(*sizes):
    return hashlib.md5(b"".join(struct.pack("<Q", n) for n in sizes)).hexdigest().upper()


class DVD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dvd = self.root / "VIDEO_TS"
        self.dvd.mkdir()

    def test_normal_dvd_hash_is_unchanged(self):
        for name, size in (("VIDEO_TS.BUP", 2), ("VIDEO_TS.IFO", 3), ("VTS_01_1.VOB", 7)):
            (self.dvd / name).write_bytes(b"x" * size)
        with patch.object(Path, "open", side_effect=AssertionError("must only read metadata")):
            self.assertEqual(discdb.fingerprint(str(self.root)),
                             {"content_hash": digest(2, 3, 7), "layout": "dvd", "files": 3})

    def test_extra_files_change_legacy_hash_but_not_filtered_hash(self):
        (self.dvd / "README.txt").write_bytes(b"extra")
        (self.dvd / "VIDEO_TS.IFO").write_bytes(b"abc")
        (self.dvd / "BACKUP").mkdir()
        (self.dvd / "BACKUP/VTS_01_1.VOB").write_bytes(b"nested")
        result = discdb.fingerprint(str(self.root))
        self.assertEqual(result, {"content_hash": digest(3), "layout": "dvd", "files": 1})
        self.assertNotEqual(result["content_hash"], digest(5, 3))

    def test_case_insensitive_extensions_and_no_media_files(self):
        (self.dvd / "notes.txt").write_bytes(b"ignored")
        self.assertIsNone(discdb.fingerprint(str(self.root)))
        (self.dvd / "video_ts.iFo").write_bytes(b"abc")
        self.assertEqual(discdb.fingerprint(str(self.root))["content_hash"], digest(3))


if __name__ == "__main__":
    unittest.main()
