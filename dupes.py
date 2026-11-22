r"""
dupes.py - spot extra copies of a movie's main feature BEFORE ripping, so only one is ripped.

Optional (setting "skip_duplicate_features", off by default). Some discs list the feature more
than once: DVDs with the same programme reachable through several titles, and Blu-rays that hide
the real playlist among dozens of same-length decoys ("playlist obfuscation"). Ripping all of them
costs 20-40 minutes per copy.

Only titles at least FEATURE_MIN_SECONDS long and within DURATION_SLACK seconds of each other are
compared, so different cuts (theatrical / extended / director's) are never touched: their running
times differ. A copy is skipped only when Shelfrip can be sure it adds nothing:

  1. Same content: the same segment map (the same clips in the same order) and the same chapter
     count, and every audio and subtitle track it has is also on the copy that is kept. Different-
     language versions use different clips for their credits or inserts, so their maps differ and
     they are kept.
  2. A disc database knows the disc: your own catalog, the shared Shelfrip database or TheDiscDB
     names exactly one of the same-length titles as the main feature, and the others are unknown
     or were skipped before. That is how decoy playlists get dropped. If the database's pick can't
     be told apart from a decoy (same byte size and no playlist name to go by), nothing is skipped.

Anything else is ripped as before. Skipped titles stay listed in disc_info.json with
"skipped_duplicate_of" set, so the Review tab can say what was left out.
"""

from __future__ import annotations

from collections import Counter

FEATURE_MIN_SECONDS = 60 * 60
DURATION_SLACK = 2


def _seg(t: dict) -> str:
    return (t.get("segments") or "").replace(" ", "")


def _tracks(t: dict) -> Counter:
    """Audio and subtitle tracks, as a multiset of what tells two tracks apart."""
    return Counter((s.get("type"), s.get("lang3") or s.get("lang"), s.get("codec"), s.get("channels"),
                    s.get("flags"), s.get("name"))
                   for s in t.get("streams", []) if s.get("type") in ("Audio", "Subtitles"))


def _groups(titles: list[dict], min_seconds: int) -> list[list[dict]]:
    longs = sorted((t for t in titles if t.get("duration_seconds", 0) >= min_seconds and t.get("output_file")),
                   key=lambda t: t["duration_seconds"])
    groups: list[list[dict]] = []
    for t in longs:
        if groups and t["duration_seconds"] - groups[-1][0]["duration_seconds"] <= DURATION_SLACK:
            groups[-1].append(t)
        else:
            groups.append([t])
    return [g for g in groups if len(g) > 1]


def _same_content(group: list[dict]) -> dict[int, tuple[int, str]]:
    out: dict[int, tuple[int, str]] = {}
    by_map: dict[tuple, list[dict]] = {}
    for t in group:
        if _seg(t):
            by_map.setdefault((_seg(t), t.get("chapters")), []).append(t)
    for same in by_map.values():
        if len(same) < 2:
            continue
        # keep the copy with the most tracks (then the lowest title number); skip only true subsets
        keep = max(same, key=lambda t: (sum(_tracks(t).values()), -t["title_id"]))
        have = _tracks(keep)
        for t in same:
            if t is not keep and not (_tracks(t) - have):
                out[t["title_id"]] = (keep["title_id"], "same clips and tracks")
    return out


def _is_main(row: dict) -> bool:
    return row.get("itemType") == "MainMovie" and row.get("kept", True) is not False


def _from_database(group: list[dict], known: dict) -> dict[int, tuple[int, str]]:
    pairs = known.get("pairs") or {}
    mains = [t for t in group if t["output_file"] in pairs and _is_main(pairs[t["output_file"]])]
    if len(mains) != 1:
        return {}  # nothing known, or several features of this length: keep them all
    keep = mains[0]
    row = pairs[keep["output_file"]]
    row_src = (row.get("sourceFile") or row.get("source_file") or "").lower()
    our_src = (keep.get("source_file") or "").split("(")[0].strip().lower()
    unique_size = sum(1 for t in group if t.get("size_bytes") == keep.get("size_bytes")) == 1
    if not ((row_src and row_src == our_src) or unique_size):
        return {}  # the database's pick could be any of the look-alikes
    src = known.get("src_name") or ("your disc catalog" if known.get("local") else "TheDiscDB")
    out = {}
    for t in group:
        if t is keep:
            continue
        other = pairs.get(t["output_file"])
        if other is None or not _is_main(other):
            out[t["title_id"]] = (keep["title_id"], f"{src} names title {keep['title_id']} as the feature")
    return out


def find(titles: list[dict], known: dict | None = None,
         min_seconds: int = FEATURE_MIN_SECONDS) -> dict[int, tuple[int, str]]:
    """{title_id to skip: (title_id kept instead, reason)} for extra copies of a long feature."""
    skip: dict[int, tuple[int, str]] = {}
    for group in _groups(titles, min_seconds):
        found = _same_content(group)
        if known:
            for tid, v in _from_database(group, known).items():
                found.setdefault(tid, v)
        # never skip the title another one is being kept in place of
        kept = {k for k, _ in found.values()}
        skip.update({tid: v for tid, v in found.items() if tid not in kept})
    return skip


def lookup_known(disc: dict, cfg: dict, log=print) -> dict | None:
    """What the disc databases know about this disc, looked up before ripping (same order as identify.py)."""
    titles = [t for t in disc.get("titles", []) if t.get("output_file")]
    try:
        import catalog
        known = catalog.lookup(disc, titles)
        if known:
            return known
    except Exception as exc:
        log(f"    (disc catalog lookup failed: {exc})")
    try:
        import community
        known = community.lookup(disc, titles, cfg, log=log)
        if known:
            return known
    except Exception as exc:
        log(f"    (Shelfrip disc database lookup failed: {exc})")
    if cfg.get("use_thediscdb", True):
        try:
            import discdb
            return discdb.lookup(disc, titles, log=log)
        except Exception as exc:
            log(f"    (TheDiscDB lookup failed: {exc})")
    return None


def plan(disc: dict, cfg: dict, log=print) -> dict[int, tuple[int, str]]:
    """Mark extra feature copies in disc["titles"] (skipped_duplicate_of) and return them. Movie-ish discs only."""
    titles = disc.get("titles", [])
    if len(_groups(titles, FEATURE_MIN_SECONDS)) == 0:
        return {}  # nothing to compare: no lookup needed
    known = lookup_known(disc, cfg, log=log)
    if known and known.get("kind") == "tv":
        return {}
    skip = find(titles, known)
    for t in titles:
        if t["title_id"] in skip:
            t["skipped_duplicate_of"], t["skip_reason"] = skip[t["title_id"]]
    return skip
