"""
epmatch.py - decide which episode each video on a disc is, all at once.

The subtitle check (subcheck.py) scores every video against every episode of the season. Taking
each video's best score on its own lets two videos claim the same episode, and lets a clip show
(an episode made of scenes from earlier ones) take a real episode's place. This module:

  1. finds clip shows first: videos whose dialogue fits many episodes about equally, or that
     fit an episode TMDB describes as a clip show, and matches them to those episodes;
  2. matches the rest with the Hungarian method (the one-to-one pairing with the best total
     score), giving a little weight to the planned number so weak evidence doesn't reshuffle
     a disc that was already right;
  3. says how sure each match is, so the review page only speaks up when the dialogue is clear.

It also scores a video's dialogue against a downloaded reference subtitle of an episode
(dialogue to dialogue), which is far stronger than plot-summary words when it's available.

Pure functions, standard library only.
"""

from __future__ import annotations

import re
import statistics
import unicodedata

# TMDB episode titles and summaries that mean "a clip show"
CLIP_WORDS = re.compile(r"\b(clip show|clip episode|highlights|look(?:s|ing)? back|retrospective|best moments|"
                        r"greatest moments|flashback episode|reminisc\w*|compilation|recap episode|"
                        r"memorable moments|favou?rite moments)\b", re.I)


def is_clip_show(name: str, overview: str) -> bool:
    return bool(CLIP_WORDS.search(f"{name or ''} {overview or ''}"))


# --------------------------------------------------------------------------- Hungarian method

def hungarian(cost: list[list[float]]) -> list[int]:
    """Minimum-cost assignment for an n x m cost matrix with n <= m. Returns, for each row, the
    column it gets (every row gets a different column). O(n^2 m)."""
    n = len(cost)
    if n == 0:
        return []
    m = len(cost[0])
    if n > m:
        raise ValueError("more rows than columns")
    INF = float("inf")
    u, v = [0.0] * (n + 1), [0.0] * (m + 1)
    p, way = [0] * (m + 1), [0] * (m + 1)   # p[j] = row (1-based) holding column j
    for i in range(1, n + 1):
        p[0] = i
        j0 = 0
        minv = [INF] * (m + 1)
        used = [False] * (m + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, m + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(m + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    out = [0] * n
    for j in range(1, m + 1):
        if p[j]:
            out[p[j] - 1] = j - 1
    return out


def best_pairs(scores: dict, rows: list, cols: list) -> dict:
    """The one-to-one pairing of rows to cols with the highest total score. When there are more
    rows than cols, the rows that fit worst are left out (absent from the result)."""
    if not rows or not cols:
        return {}
    pad = max(0, len(rows) - len(cols))
    cols_p = list(cols) + [None] * pad          # dummy episodes for rows left without one
    top = max((scores[r].get(c, 0.0) for r in rows for c in cols), default=0.0)
    cost = [[top - (scores[r].get(c, 0.0) if c is not None else -1.0) for c in cols_p] for r in rows]
    pick = hungarian(cost)
    return {r: cols_p[k] for r, k in zip(rows, pick) if cols_p[k] is not None}


# --------------------------------------------------------------------------- the whole disc

def breadth(row: dict[int, float], share: float = 0.6) -> int:
    """How many episodes this video fits nearly as well as its best one."""
    best = max(row.values(), default=0.0)
    if best <= 0:
        return 0
    return sum(1 for s in row.values() if s >= share * best)


def assign(scores: dict, planned: dict, clip_eps: set | None = None, prior: float = 0.15,
           wide: int | None = None) -> dict:
    """Match every video (row) to an episode.

    scores:   {row: {episode: score}}, higher = fits better
    planned:  {row: episode number Shelfrip planned, or None}
    clip_eps: episodes TMDB describes as clip shows
    prior:    share of a typical best score added to each row's planned episode, so that a disc
              that was numbered right stays that way unless the dialogue clearly says otherwise
              (0 for a folder of files whose order means nothing)
    wide:     a row fitting at least this many episodes nearly equally is a clip show
              (default: 4, or a third of the season if that's more)

    Returns {row: {"episode", "score", "second", "margin", "clip_show"}}; rows with nothing to go
    on get episode None.
    """
    clip_eps = set(clip_eps or ())
    rows = [r for r in scores if max(scores[r].values(), default=0) > 0]
    eps = sorted({e for r in scores for e in scores[r]})
    if not rows or not eps:
        return {r: {"episode": None, "score": 0.0, "second": 0.0, "margin": 0.0, "clip_show": False} for r in scores}
    wide = wide or max(4, len(eps) // 3)
    tops = [max(scores[r].values()) for r in rows]
    bonus = prior * statistics.median(tops)
    adj = {r: {e: s + (bonus if planned.get(r) == e else 0.0) for e, s in scores[r].items()} for r in rows}

    # 1. clip shows first: they fit many episodes, so taken last they'd steal one
    clip_rows = [r for r in rows if breadth(scores[r]) >= wide
                 or max(scores[r], key=scores[r].get) in clip_eps]
    out: dict = {}
    taken: set = set()
    if clip_rows:
        targets = sorted(clip_eps) or []
        pairs = best_pairs(adj, clip_rows, targets) if targets else {}
        for r in clip_rows:
            e = pairs.get(r)
            if e is None and planned.get(r) is not None and planned[r] not in clip_eps:
                # no clip show listed for it: a wide row keeps its planned number, but doesn't
                # get to push a real episode out of the way
                e = planned[r]
            if e is not None and e not in taken:
                out[r] = e
                taken.add(e)
    # 2. everything else, one-to-one with the best total score
    rest = [r for r in rows if r not in out]
    free = [e for e in eps if e not in taken]
    out.update(best_pairs(adj, rest, free))

    result = {}
    for r in scores:
        e = out.get(r)
        row = scores[r]
        s = row.get(e, 0.0) if e is not None else 0.0
        second = max((v for k, v in row.items() if k != e), default=0.0)
        result[r] = {"episode": e, "score": s, "second": second,
                     "margin": (s / second) if second > 0 else (float("inf") if s > 0 else 0.0),
                     "clip_show": r in clip_rows}
    return result


# --------------------------------------------------------------------------- dialogue vs reference

def _fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower().replace("’", "'")


def shingles(text: str, n: int = 3) -> set[tuple]:
    """Runs of n words within each subtitle line (lines are where OCR and timing differ least)."""
    out = set()
    for line in (text or "").splitlines():
        ws = re.findall(r"[a-z0-9']+", _fold(line))
        for k in range(len(ws) - n + 1):
            out.add(tuple(ws[k:k + n]))
    return out


def srt_text(raw: str) -> str:
    """The spoken lines of an .srt file, one cue per line, without numbers, times or tags."""
    out = []
    for block in re.split(r"\n\s*\n", (raw or "").replace("\r", "")):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        lines = [ln for ln in lines if not re.fullmatch(r"\s*\d+\s*", ln) and "-->" not in ln]
        text = re.sub(r"<[^>]+>|\{[^}]*\}|\[[^\]]*\]|\([A-Z ]+\)", " ", " ".join(lines))
        text = re.sub(r"^\s*-\s*|\s+", " ", text).strip()
        if text:
            out.append(text)
    return "\n".join(out)


def containment(sample: set, ref: set) -> float:
    """Share of the video's word runs found in the reference."""
    return len(sample & ref) / len(sample) if sample else 0.0


def reference_scores(sample_text: str, refs: dict[int, set], scale: float = 10.0) -> dict[int, float]:
    """Score one video's dialogue against each episode's reference subtitles. Everyday phrases
    ("i don't know") appear in every episode, so the episode's median share is taken off first.
    Scaled to sit above the plot-summary scores (which rarely pass 3)."""
    sample = shingles(sample_text)
    raw = {e: containment(sample, r) for e, r in refs.items() if r}
    if not raw:
        return {}
    base = statistics.median(raw.values()) if len(raw) >= 3 else 0.0
    return {e: max(0.0, c - base) * scale for e, c in raw.items()}


def mislabeled(refs: dict[int, set], same: float = 0.6) -> set[int]:
    """Reference files that are really another episode's subtitles (uploaders mislabel them):
    two episodes whose references share most of their lines. Both are dropped, as there's no
    telling which one is right."""
    bad = set()
    keys = [e for e in refs if refs[e]]
    for i, a in enumerate(keys):
        for b in keys[i + 1:]:
            small = min(len(refs[a]), len(refs[b])) or 1
            if len(refs[a] & refs[b]) / small >= same:
                bad |= {a, b}
    return bad
