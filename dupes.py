r"""
dupes.py - spot extra copies of a movie or an episode BEFORE ripping, so each is ripped once.

Optional (setting "skip_duplicate_features", off by default). Some discs list the same video more
than once: DVDs with the same programme reachable through several titles, Blu-rays that hide the
real playlist among dozens of same-length decoys ("playlist obfuscation"), and TV Blu-rays (Game of
Thrones in 4K, for one) that list every episode twice, as its playlist and as its raw .m2ts file.
Ripping all of them costs 20-40 minutes and up to 30 GB per copy.

Only titles within DURATION_SLACK seconds of each other are compared, so different cuts (theatrical /
extended / director's) are never touched: their running times differ. A copy is skipped only when
Shelfrip can be sure it adds nothing:

  1. Same content (any title COPY_MIN_SECONDS or longer): every audio and subtitle track it has is
     also on the copy that is kept, and
       * Blu-ray: it plays the same clips in the same order (a raw .m2ts title plays its own clip).
         Chapter marks don't count: the playlist, which has them, is the copy kept.
       * DVD (cell numbers are per title): the same cell map and chapter count, and below feature
         length the same byte size too, as a TV DVD's episodes all read "cells 1-6".
     Different-language versions use different clips for their credits or inserts, so their maps
     differ and they are kept. When a disc database names both copies as different things, both
     are kept.
  2. A disc database knows the disc (movies, FEATURE_MIN_SECONDS or longer): your own catalog, the
     shared Shelfrip database or TheDiscDB names exactly one of the same-length titles as the main
     feature, and the others are unknown or were skipped before. That is how decoy playlists get
     dropped. If the database's pick can't be told apart from a decoy (same byte size and no
     playlist name to go by), nothing is skipped.

The same setting also leaves out scene-by-scene titles: discs that offer every scene (or chapter)
of the movie as a title of its own, next to the movie itself. Those are the movie a second time,
cut into pieces, and make Review slow. A short title counts as a scene only when:

  * Blu-ray: it is made only of the feature's own video clips (its segment map is inside the
    feature's), at least SCENE_MIN_PIECES such titles exist, each is under SCENE_MAX_SECONDS and
    shorter than half the feature, and the feature looks like a movie rather than a "Play All" of
    featurettes (more clips than chapters, or one clip, or a disc database names it the feature).
  * DVD (cell numbers aren't shared between titles): a run of at least four consecutive short titles
    adds up to the feature's length and there are about as many as the feature has chapters; or at
    least DVD_SAME_TRACKS_PIECES short titles carry exactly the feature's audio and subtitle tracks
    (its dubs, commentary and subtitles: extras almost never do) and the feature has at least
    DVD_MIN_TRACKS of them.

Scenes are looked for on movie discs only. On TV discs the setting instead leaves out a "Play All"
title (every episode in one video) when its episodes are also titles of their own and are ripped:

  * Blu-ray: the Play All plays nothing but the episodes' clips, every one of them, and the
    episodes add up to its length.
  * DVD: two or more titles in a row (by title number) add up to its length to within a few seconds.
  * Either way, each episode carries every soundtrack and subtitle the Play All has.

A TV disc with only the Play All keeps it: it's split into episodes on the Review tab. Titles a
disc database names are always ripped. Nothing is lost: everything in a skipped title is in one
that is ripped.

Anything else is ripped as before. Skipped titles stay listed in disc_info.json with
"skipped_duplicate_of" set and "skip_kind" saying why ("copy", "scene" or "play_all"), so the
Review tab can say what was left out. scene_pieces() is also used by identify.py to set leftover
scenes to Skip on Review.
"""

from __future__ import annotations

from collections import Counter

FEATURE_MIN_SECONDS = 60 * 60
COPY_MIN_SECONDS = 5 * 60     # identical copies (same clips and tracks) are left out from this length up
DURATION_SLACK = 2
SCENE_MAX_SECONDS = 15 * 60
SCENE_MIN_PIECES = 3
DVD_MIN_PIECES = 4
DVD_MIN_TRACKS = 4           # feature audio + subtitle tracks needed before matching tracks mean anything
DVD_SAME_TRACKS_PIECES = 5   # short titles carrying exactly those tracks


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


def _clips(t: dict) -> tuple[str, ...] | None:
    """The Blu-ray clips a title plays, in order. None on DVDs, where segment numbers are per title.
    A raw .m2ts title plays just its own clip."""
    src = str(t.get("source_file") or "").split("(")[0].strip().lower()
    if not src.endswith((".mpls", ".m2ts")):
        return None
    clips = tuple(x for x in _seg(t).split(",") if x)
    if not clips and src.endswith(".m2ts") and src[:-5].isdigit():
        clips = (str(int(src[:-5])),)
    return clips or None


def _content_key(t: dict) -> tuple | None:
    """Titles with the same key show the same video. Blu-ray: the same clips in the same order
    (chapter marks don't matter: a playlist and its raw .m2ts have the same picture, only one has
    chapters). DVD: the same cells and chapters, and below feature length the same byte size too,
    since a TV DVD's episodes all read "cells 1-6" and can run to the same second."""
    clips = _clips(t)
    if clips is not None:
        return ("bd", clips)
    if not _seg(t):
        return None
    if t.get("duration_seconds", 0) >= FEATURE_MIN_SECONDS:
        return ("dvd", _seg(t), t.get("chapters"))
    return ("dvd", _seg(t), t.get("chapters"), t["size_bytes"]) if t.get("size_bytes") else None


def _named(t: dict, known: dict | None) -> dict | None:
    """The disc database's row for a title it names (and didn't skip), else None."""
    row = ((known or {}).get("pairs") or {}).get(t.get("output_file"))
    return row if row and row.get("kept", True) is not False else None


def _row_name(row: dict) -> tuple:
    return tuple(str(row.get(k) or "").strip().lower() for k in ("itemType", "season", "episode", "description", "name"))


def _same_content(group: list[dict], known: dict | None = None) -> dict[int, tuple[int, str]]:
    out: dict[int, tuple[int, str]] = {}
    by_key: dict[tuple, list[dict]] = {}
    for t in group:
        key = _content_key(t)
        if key:
            by_key.setdefault(key, []).append(t)
    for same in by_key.values():
        if len(same) < 2:
            continue
        # keep the copy with the most tracks, then one a disc database names, then a playlist (it has
        # chapters) over a raw clip, then the lowest title number; skip only true subsets
        keep = max(same, key=lambda t: (sum(_tracks(t).values()), _named(t, known) is not None,
                                        not str(t.get("source_file") or "").lower().endswith(".m2ts"),
                                        int(t.get("chapters") or 0) > 0, -t["title_id"]))
        have, kept_row = _tracks(keep), _named(keep, known)
        for t in same:
            if t is keep or _tracks(t) - have:
                continue
            row = _named(t, known)
            if row and kept_row and _row_name(row) != _row_name(kept_row):
                continue  # a database says they're different things: rip both
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
         min_seconds: int = FEATURE_MIN_SECONDS, tv: bool = False) -> dict[int, tuple[int, str]]:
    """{title_id to skip: (title_id kept instead, reason)} for extra copies of a title: any title of
    COPY_MIN_SECONDS or more shown twice with the same clips and tracks (a TV episode as a playlist
    and as its raw .m2ts), and look-alike copies of a feature (min_seconds or more) that a disc
    database tells apart (movie discs only: a TV disc's database rows name episodes)."""
    skip: dict[int, tuple[int, str]] = {}
    for group in _groups(titles, min(COPY_MIN_SECONDS, min_seconds)):
        found = _same_content(group, known)
        if known and not tv and group[0]["duration_seconds"] >= min_seconds:
            for tid, v in _from_database(group, known).items():
                found.setdefault(tid, v)
        # never skip the title another one is being kept in place of
        kept = {k for k, _ in found.values()}
        skip.update({tid: v for tid, v in found.items() if tid not in kept})
    return skip


# --------------------------------------------------------------------------- TV "Play All" titles

def _bd_play_all(p: dict, ripped: list[dict]) -> list[dict]:
    """Episodes (2 or more) a Blu-ray "Play All" playlist strings together: every clip it plays is in
    one of them, they play nothing else, and they add up to its length."""
    pc = _clips(p)
    if not pc or len(set(pc)) < 2:
        return []
    pieces = [t for t in ripped if t is not p and COPY_MIN_SECONDS <= t.get("duration_seconds", 0) < p["duration_seconds"]
              and (c := _clips(t)) is not None and set(c) <= set(pc)]
    by_clips: dict[tuple, dict] = {}
    for t in pieces:
        by_clips.setdefault(_clips(t), t)
    pieces = list(by_clips.values())
    covered = set().union(*(set(_clips(t)) for t in pieces)) if pieces else set()
    total = sum(t["duration_seconds"] for t in pieces)
    if len(pieces) < 2 or covered != set(pc) or abs(total - p["duration_seconds"]) > max(10, 0.01 * p["duration_seconds"]):
        return []
    return pieces


def _dvd_play_all(p: dict, ripped: list[dict]) -> list[dict]:
    """Episodes (2 or more, one after another by title number) that add up to a DVD "Play All" title."""
    if _clips(p) is not None:
        return []
    pd = p["duration_seconds"]
    others = sorted((t for t in ripped if t is not p and _clips(t) is None), key=lambda t: t["title_id"])
    for i in range(len(others)):
        total = 0
        for j in range(i, len(others)):
            d = others[j].get("duration_seconds", 0)
            if not COPY_MIN_SECONDS <= d < pd:
                break
            total += d
            n = j - i + 1
            slack = max(5, 2 * n)
            if total > pd + slack:
                break
            if n >= 2 and abs(total - pd) <= slack:
                return others[i:j + 1]
    return []


def play_alls(titles: list[dict], known: dict | None = None,
              skip: dict | None = None) -> dict[int, tuple[int, str]]:
    """{title_id: (first episode's title_id, reason)} for a TV disc's "Play All" titles whose episodes
    are also on the disc as titles of their own (and are being ripped). Each episode must carry every
    soundtrack and subtitle the Play All has. A disc with only the Play All keeps it (it's split into
    episodes later), and titles a disc database names are always ripped."""
    skip = skip or {}
    ripped = [t for t in titles if t.get("output_file") and t["title_id"] not in skip]
    out: dict[int, tuple[int, str]] = {}
    for p in sorted(ripped, key=lambda t: -t.get("duration_seconds", 0)):
        if p.get("duration_seconds", 0) < 2 * COPY_MIN_SECONDS or _named(p, known):
            continue
        left = [t for t in ripped if t["title_id"] not in out]
        pieces = _bd_play_all(p, left) or _dvd_play_all(p, left)
        if not pieces or any(_tracks(p) - _tracks(t) for t in pieces):
            continue
        ids = sorted(t["title_id"] for t in pieces)
        out[p["title_id"]] = (ids[0], "a Play All of titles " + ", ".join(map(str, ids)) + ", which are ripped on their own")
    return out


# --------------------------------------------------------------------------- scene-by-scene titles

def _segset(t: dict) -> set[str] | None:
    """The Blu-ray clips a title plays. None on DVDs, where segment numbers are per title and can't be compared."""
    src = str(t.get("source_file") or "").split("(")[0].strip().lower()
    if not src.endswith((".mpls", ".m2ts")):
        return None
    return {x for x in _seg(t).split(",") if x} or None


def _movie_shaped(f: dict) -> bool:
    """A "Play All" of featurettes has one clip per chapter; a movie has one clip, or many more clips than chapters."""
    n = len(_segset(f) or ())
    return n == 1 or n > int(f.get("chapters") or 0)


def _dvd_run(others: list[dict], f: dict, stop: set[int]) -> list[dict]:
    """Consecutive short titles (by title number) that add up to the feature, about one per chapter."""
    ch, fd = int(f.get("chapters") or 0), f["duration_seconds"]
    if ch < DVD_MIN_PIECES:
        return []
    for i in range(len(others)):
        total = 0
        for j in range(i, len(others)):
            d = others[j].get("duration_seconds", 0)
            if d >= SCENE_MAX_SECONDS or others[j]["title_id"] in stop or _segset(others[j]) is not None:
                break
            total += d
            n = j - i + 1
            slack = max(15, 0.01 * fd, 2 * n)
            if total > fd + slack:
                break
            if n >= DVD_MIN_PIECES and ch - 2 <= n <= ch + 1 and abs(total - fd) <= slack:
                return others[i:j + 1]
    return []


def scene_pieces(titles: list[dict], features: list[dict], trusted: set[int] | frozenset = frozenset(),
                 keep: set[int] | frozenset = frozenset()) -> dict[int, tuple[int, str]]:
    """{title_id: (feature title_id, reason)} for short titles that are scenes of one of `features`.

    trusted: feature title_ids known to be the movie (a database or TMDB said so), which skips the
    "looks like a movie" check. keep: title_ids never to report (named by a database)."""
    out: dict[int, tuple[int, str]] = {}
    fids = {f["title_id"] for f in features}
    for f in sorted(features, key=lambda f: -f["duration_seconds"]):
        fd = f["duration_seconds"]
        others = sorted((t for t in titles if t["title_id"] not in fids), key=lambda t: t["title_id"])
        fs = _segset(f)
        if fs is not None:
            if f["title_id"] not in trusted and not _movie_shaped(f):
                continue
            pieces = [t for t in others if t["title_id"] not in out and t["title_id"] not in keep
                      and 0 < t.get("duration_seconds", 0) < min(SCENE_MAX_SECONDS, fd / 2)
                      and (s := _segset(t)) is not None and s <= fs]
            if len(pieces) < SCENE_MIN_PIECES:
                continue
            why = "only plays clips of the feature"
        else:
            pieces = _dvd_run(others, f, set(keep) | set(out))
            why = "it and the titles next to it add up to the feature, chapter by chapter"
            sig = _tracks(f)
            if not pieces and sum(sig.values()) >= DVD_MIN_TRACKS:
                pieces = [t for t in others if t["title_id"] not in out and t["title_id"] not in keep
                          and 0 < t.get("duration_seconds", 0) < min(SCENE_MAX_SECONDS, fd / 2)
                          and _segset(t) is None and _tracks(t) == sig]
                if len(pieces) < DVD_SAME_TRACKS_PIECES:
                    pieces = []
                why = "it has exactly the feature's soundtracks and subtitles, like the other scenes"
        for t in pieces:
            out[t["title_id"]] = (f["title_id"], f"a scene of title {f['title_id']}: {why}")
    return out


def _tv_like(disc: dict, titles: list[dict], unsure: bool = True) -> bool:
    try:
        import identify
        info = identify.parse_label(disc.get("disc_label") or disc.get("volume_label") or disc.get("name") or "")
        return identify.looks_like_tv(titles, info, None)
    except Exception:
        return unsure  # can't tell: whichever leaves the disc alone


def find_scenes(disc: dict, known: dict | None, skip: dict | None = None) -> dict[int, tuple[int, str]]:
    """Scene-by-scene titles to leave out before ripping (movie discs only)."""
    titles = [t for t in disc.get("titles", []) if t.get("output_file")]
    skip = skip or {}
    features = [t for t in titles if t.get("duration_seconds", 0) >= FEATURE_MIN_SECONDS and t["title_id"] not in skip]
    if not features or (known and known.get("kind") == "tv") or _tv_like(disc, titles):
        return {}
    pairs = (known or {}).get("pairs") or {}
    trusted = {t["title_id"] for t in features if t["output_file"] in pairs and _is_main(pairs[t["output_file"]])}
    named = {t["title_id"] for t in titles if t["output_file"] in pairs and pairs[t["output_file"]].get("kept", True) is not False}
    return scene_pieces(titles, features, trusted, keep=named)


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
    """Mark extra copies, scene-by-scene titles and TV Play Alls in disc["titles"] (skipped_duplicate_of,
    skip_reason, skip_kind) and return them all."""
    titles = disc.get("titles", [])
    if not _groups(titles, COPY_MIN_SECONDS) and not find_scenes(disc, None) and not play_alls(titles):
        return {}  # nothing to leave out even before asking the databases: no lookup needed
    known = lookup_known(disc, cfg, log=log)
    usable = [t for t in titles if t.get("output_file")]
    is_tv = bool(known and known.get("kind") == "tv")
    skip = find(titles, known, tv=is_tv or _tv_like(disc, usable))
    scenes = {} if is_tv else find_scenes(disc, known, skip)
    plays = play_alls(titles, known, skip) if is_tv or _tv_like(disc, usable, unsure=False) else {}
    for t in titles:
        if t["title_id"] in skip:
            t["skipped_duplicate_of"], t["skip_reason"] = skip[t["title_id"]]
            t["skip_kind"] = "copy"
        elif t["title_id"] in scenes:
            t["skipped_duplicate_of"], t["skip_reason"] = scenes[t["title_id"]]
            t["skip_kind"] = "scene"
        elif t["title_id"] in plays:
            t["skipped_duplicate_of"], t["skip_reason"] = plays[t["title_id"]]
            t["skip_kind"] = "play_all"
    return {**skip, **scenes, **plays}
