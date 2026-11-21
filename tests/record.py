r"""
record.py - make the naming fixtures from the discs you've filed. Run it on a PC with
internet and your keys:

    python tests\record.py "D:\Ripped"

For each disc in <rip folder>\_Filed it saves the disc's records and how Shelfrip names it
today (tests\fixtures\<disc>\), plus every web answer that naming used (tests\fixtures\http.json,
with keys removed). Run it again after a change that's meant to rename things, and look at the
difference before trusting the new names.

The fixtures are your own discs, so they stay on your PC: tests\fixtures is never committed
(it's in .gitignore). GitHub runs the other tests, which use made-up discs.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import discs  # noqa: E402
import net  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit("Usage: python tests/record.py <your rip folder>")
    rip_root = Path(sys.argv[1])
    filed = sorted(d for d in (rip_root / "_Filed").iterdir() if (d / "disc_info.json").exists()
                   and (d / "plan.json").exists())
    # your settings, read directly: Shelfrip itself must start in a throwaway folder (below), so your
    # learned labels and disc database can't answer for the web services being recorded
    real_cfg = Path(os.environ.get("SHELFRIP_DATA") or Path(os.environ.get("APPDATA") or Path.home()) / "Shelfrip") / "config.json"
    real = json.loads(real_cfg.read_text(encoding="utf-8-sig"))
    secrets = [str(real.get(k) or "") for k in real if any(p in k.lower() for p in ("key", "token", "secret"))]
    fcfg = discs.fixture_config(real)
    tmp = discs.setup_env({**fcfg, **{k: real.get(k, "") for k in discs.HAS_KEYS if fcfg.get(k)}})
    discs.FIXTURES.mkdir(exist_ok=True)
    (discs.FIXTURES / "config.json").write_text(json.dumps(fcfg, indent=2), encoding="utf-8")
    rec = net.Recorder()
    urllib.request.urlopen = rec
    n = 0
    for d in filed:
        plan = json.loads((d / "plan.json").read_text(encoding="utf-8"))
        if plan.get("kind") not in ("movie", "tv") or plan.get("status") != "filed":
            continue
        fix = discs.FIXTURES / d.name
        fix.mkdir(exist_ok=True)
        for name in ("disc_info.json", "makemkv_info.txt"):
            if (d / name).exists():
                text = (d / name).read_text(encoding="utf-8", errors="replace")
                (fix / name).write_text(net.scrub(text, secrets), encoding="utf-8")
        (fix / "fixture.json").write_text(json.dumps({"folder": d.name}, indent=2), encoding="utf-8")
        folder = discs.lay_out(fix, tmp / "rip")
        got = discs.name_disc(folder, tmp / "rip", real.get("tmdb_api_key", ""))
        (fix / "expected.json").write_text(json.dumps(got, indent=2, ensure_ascii=False), encoding="utf-8")
        # what you actually filed, for comparison (not checked by the tests)
        (fix / "filed.json").write_text(json.dumps(discs.summary(plan), indent=2, ensure_ascii=False), encoding="utf-8")
        shutil.rmtree(folder)
        n += 1
        print(f"{d.name}: {got.get('title')} ({len(got.get('items', []))} titles)")
    net.dump(rec.log, discs.FIXTURES / "http.json", secrets)
    print(f"Recorded {n} disc(s) and {len(rec.log)} web answers into {discs.FIXTURES}")


if __name__ == "__main__":
    main()
