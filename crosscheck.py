r"""
crosscheck.py - second opinions from other databases (used by identify.py).

  * TVmaze (api.tvmaze.com, free, no key): episode names and run times for a show,
    found via the IMDb / TheTVDB id TMDB gives us, or by name.
  * OMDb (omdbapi.com, IMDb data): a movie's run time and year. Needs a free key in
    config.json as "omdb_api_key" (get one at https://www.omdbapi.com/apikey.aspx).

Both are only used to double-check TMDB, never to overrule your review. Every
lookup is cached in .cache/ and any network failure just skips the check.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse

TVMAZE = "https://api.tvmaze.com"
OMDB = "https://www.omdbapi.com/"


def _get_json(url: str, cache_key: str, max_age_days: int = 7):
    import extras

    def fetch():
        try:
            return json.loads(extras._http(url))
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise
    return extras._cached(cache_key, fetch, max_age_days=max_age_days)


# --------------------------------------------------------------------------- TVmaze

def tvmaze_show(tmdb, tmdb_id: str, title: str, year: str = "") -> dict | None:
    """Find the show on TVmaze: by IMDb id, then TheTVDB id, then by name (+ year)."""
    ext = {}
    if tmdb and tmdb_id:
        try:
            ext = tmdb.get(f"/tv/{int(tmdb_id)}/external_ids")
        except Exception:
            ext = {}
    for key, val in (("imdb", ext.get("imdb_id")), ("thetvdb", ext.get("tvdb_id"))):
        if val:
            show = _get_json(f"{TVMAZE}/lookup/shows?{key}={urllib.parse.quote(str(val))}", f"tvmaze:{key}:{val}")
            if show and show.get("id"):
                return show
    if title:
        res = _get_json(f"{TVMAZE}/search/shows?q={urllib.parse.quote(title)}", f"tvmaze:q:{title.lower()}") or []
        for r in res:
            s = r.get("show") or {}
            if not year or str(s.get("premiered") or "")[:4] == str(year):
                return s
    return None


def tvmaze_season(tmdb, tmdb_id: str, title: str, year: str, season: int) -> dict | None:
    """{'show': name, 'episodes': {number: {'name', 'runtime'}}} for one season (0 = specials)."""
    show = tvmaze_show(tmdb, tmdb_id, title, year)
    if not show:
        return None
    eps = _get_json(f"{TVMAZE}/shows/{show['id']}/episodes?specials=1", f"tvmaze:eps:{show['id']}") or []
    out: dict[int, dict] = {}
    specials = 0
    for e in eps:
        if e.get("number") is None:  # TVmaze lists specials without a number
            specials += 1
            if season == 0:
                out[specials] = {"name": e.get("name") or "", "runtime": e.get("runtime")}
            continue
        if e.get("season") == season:
            out[int(e["number"])] = {"name": e.get("name") or "", "runtime": e.get("runtime")}
    return {"show": show.get("name") or "", "id": show["id"], "episodes": out,
            "runtime": show.get("averageRuntime") or show.get("runtime")}


def same_name(a: str, b: str) -> bool:
    n = lambda s: re.sub(r"[^a-z0-9]", "", (s or "").lower().replace("&", "and"))
    a, b = n(a), n(b)
    if not a or not b:
        return True  # nothing to compare
    return a == b or a in b or b in a


# --------------------------------------------------------------------------- OMDb

def omdb_movie(key: str, imdb_id: str = "", title: str = "", year: str = "") -> dict | None:
    """{'title', 'year', 'runtime'} (runtime in minutes, or 0) from OMDb, or None."""
    if not key or "paste" in key:
        return None
    if imdb_id:
        q = {"i": imdb_id}
    elif title:
        q = {"t": title, "type": "movie", **({"y": year} if year else {})}
    else:
        return None
    url = OMDB + "?" + urllib.parse.urlencode(dict(q, apikey=key.strip()))
    data = _get_json(url, "omdb:" + json.dumps(q, sort_keys=True), max_age_days=30)
    if not data or data.get("Response") != "True":
        return None
    m = re.search(r"(\d+)\s*min", data.get("Runtime") or "")
    return {"title": data.get("Title") or "", "year": (data.get("Year") or "")[:4],
            "runtime": int(m.group(1)) if m else 0}
