"""
test_split_cut.py - cutting an episode out of a long video when one track stops early. Fairy Tail,
2026-11-26: the commentary covered only episode 1, and every later cut that reached the end of the
video came out 7345s long instead of 1508s until that track was left out of the cut.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402

discs.setup_env({"tmdb_api_key": ""})
import split  # noqa: E402

TRACKS = [{"id": 0, "type": "video", "codec": "MPEG-1/2", "properties": {}},
          {"id": 1, "type": "audio", "codec": "AC-3", "properties": {"language": "eng", "audio_channels": 6}},
          {"id": 2, "type": "audio", "codec": "AC-3", "properties": {"language": "jpn", "audio_channels": 2}},
          {"id": 3, "type": "audio", "codec": "AC-3", "properties": {"language": "eng", "audio_channels": 2,
                                                                     "track_name": "Commentary"}},
          {"id": 4, "type": "subtitles", "codec": "VobSub", "properties": {"language": "eng"}}]
SPLIT = {"chapters": [0, 1466.9, 7303.8], "starts": [0, 1, 2], "total": 8811.7, "names": ["a", "b", "c"]}


def fake_mkvmerge(cmds):
    """subprocess.run stand-in: a cut that keeps the commentary track comes out hours too long."""
    def run(cmd, **kw):
        out = mock.Mock(returncode=0, stdout="", stderr="")
        if cmd[1] == "-J":
            p = Path(cmd[2])
            if p.name == "src.mkv":
                out.stdout = __import__("json").dumps({"tracks": TRACKS, "container": {"properties": {"duration": 8811.7e9}}})
            else:
                kept = p.read_text()
                tracks = [t for t in TRACKS if t["id"] != 3]  # the commentary never makes it into the cut
                dur = 1508e9 if kept == "no-commentary" else 7345e9
                out.stdout = __import__("json").dumps({"tracks": tracks, "container": {"properties": {"duration": dur}}})
            return out
        cmds.append(cmd)
        o = Path(cmd[cmd.index("-o") + 1])
        o.write_text("no-commentary" if "-a" in cmd and "3" not in cmd[cmd.index("-a") + 1].split(",") else "all")
        return out
    return run


class CutWithEarlyEndingTrack(unittest.TestCase):
    def test_retries_without_the_track_that_ended(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "src.mkv"
        src.write_text("")
        cmds = []
        with mock.patch.object(split, "tool", lambda cfg, n: n), \
             mock.patch.object(split.subprocess, "run", fake_mkvmerge(cmds)), \
             mock.patch.object(split, "renumber_chapters", lambda *a: None):
            out = split.cut(src, SPLIT, 2, tmp / "ep" / "03.mkv", {})
        self.assertTrue(out.exists())
        self.assertEqual(len(cmds), 2)
        self.assertEqual(cmds[1][cmds[1].index("-a") + 1], "1,2")
        self.assertNotIn("-s", cmds[1])  # the subtitles were fine, so they stay

    def test_still_fails_when_no_track_is_to_blame(self):
        tmp = Path(tempfile.mkdtemp())
        src = tmp / "src.mkv"
        src.write_text("")
        global TRACKS
        saved, TRACKS[:] = list(TRACKS), [t for t in TRACKS if t["id"] != 3]
        try:
            with mock.patch.object(split, "tool", lambda cfg, n: n), \
                 mock.patch.object(split.subprocess, "run", fake_mkvmerge([])), \
                 mock.patch.object(split, "renumber_chapters", lambda *a: None):
                with self.assertRaisesRegex(RuntimeError, "came out 7345s long"):
                    split.cut(src, SPLIT, 2, tmp / "ep" / "03.mkv", {})
        finally:
            TRACKS[:] = saved


if __name__ == "__main__":
    unittest.main()
