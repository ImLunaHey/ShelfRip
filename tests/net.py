"""
net.py - record the web answers a disc's naming used, then play them back.

Naming a disc asks TMDB, TheDiscDB, OMDb, TVmaze, DVDCompare and the Shelfrip disc database.
For a test to say "this disc is still named the same way", those answers must be the same
every time, and GitHub's test machines have no keys. So record.py saves every answer once
(keys stripped from the addresses), and the tests play them back with no internet at all.
"""

from __future__ import annotations

import email.message
import hashlib
import io
import json
import re
import urllib.error
import urllib.parse
import urllib.request

SECRET_PARAMS = {"api_key", "apikey", "key", "token", "x-plex-token"}


def _key(req) -> str:
    if isinstance(req, str):
        url, body, method = req, None, "GET"
    else:
        url, body, method = req.full_url, req.data, req.get_method()
    u = urllib.parse.urlsplit(url)
    q = sorted((k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
               if k.lower() not in SECRET_PARAMS)
    k = f"{method} {u.scheme}://{u.netloc}{u.path}?{urllib.parse.urlencode(q)}"
    if body:
        k += " #" + hashlib.sha256(body if isinstance(body, bytes) else str(body).encode()).hexdigest()[:16]
    return k


class _Resp(io.BytesIO):
    def __init__(self, body: bytes, status: int = 200, url: str = ""):
        super().__init__(body)
        self.status = self.code = status
        self.url = url
        self.headers = email.message.Message()

    def getcode(self):
        return self.status

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class Recorder:
    """Real requests, with every answer kept in self.log."""

    def __init__(self):
        self.log: dict[str, dict] = {}
        self.real = urllib.request.urlopen

    def __call__(self, req, *a, **kw):
        k = _key(req)
        try:
            with self.real(req, *a, **kw) as r:
                body = r.read()
            self.log[k] = {"status": 200, "body": body.decode("utf-8", "replace")}
            return _Resp(body, 200, k)
        except urllib.error.HTTPError as exc:
            body = exc.read() or b""
            self.log[k] = {"status": exc.code, "body": body.decode("utf-8", "replace")}
            raise urllib.error.HTTPError(exc.url, exc.code, exc.msg, exc.headers, io.BytesIO(body)) from None
        except Exception as exc:
            self.log[k] = {"status": 0, "body": type(exc).__name__}
            raise


class Player:
    """Answers from a recording; anything not recorded behaves like being offline."""

    def __init__(self, log: dict):
        self.log = log
        self.missed: list[str] = []

    def __call__(self, req, *a, **kw):
        k = _key(req)
        hit = self.log.get(k)
        if hit is None or hit["status"] == 0:
            if hit is None:
                self.missed.append(k)
            raise urllib.error.URLError("not recorded (offline test)")
        if hit["status"] != 200:
            raise urllib.error.HTTPError(k, hit["status"], "recorded error", email.message.Message(),
                                         io.BytesIO(hit["body"].encode("utf-8")))
        return _Resp(hit["body"].encode("utf-8"), 200, k)


def scrub(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s and len(s) >= 6:
            text = text.replace(s, "REDACTED")
    return re.sub(r"(api_key|apikey|X-Plex-Token)=[^&\"\s]+", r"\1=REDACTED", text)


def dump(log: dict, path, secrets: list[str]) -> None:
    path.write_text(scrub(json.dumps(log, indent=1, sort_keys=True, ensure_ascii=False), secrets), encoding="utf-8")
